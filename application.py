# -------------------- IMPORTS --------------------

# Handles creation and management of DynamoDB connections
from dynamodb.connectionManager     import ConnectionManager

# Handles all game-related operations (create game, update board, etc.)
from dynamodb.gameController        import GameController

# Game model class used to wrap DynamoDB items into Python objects
from models.game                    import Game

# Used to generate unique IDs (gameId, secret keys)
from uuid                           import uuid4

# Flask framework imports for web routing, templates, sessions, redirects, JSON, etc.
from flask                          import Flask, render_template, request, session, flash, redirect, jsonify, json

# Used to read configuration from .ini files
from configparser                   import ConfigParser

# Standard Python libraries
import os, time, sys, argparse

# -------------------- FLASK APP INITIALIZATION --------------------

# Create Flask application instance
application = Flask(__name__)

# Enable Flask debug mode (auto-reload, error traces)
application.debug = True

# Secret key used by Flask to secure sessions
application.secret_key = str(uuid4())

"""
Configure the application according to the command line args and config files
"""

# Will hold the DynamoDB connection manager
cm = None

# -------------------- COMMAND LINE ARGUMENTS --------------------

# Argument parser for running the app from terminal
parser = argparse.ArgumentParser(description='Run the TicTacToe sample app', prog='application.py')

# Optional config file argument
parser.add_argument('--config', help='Path to the config file containing application settings. Cannot be used if the CONFIG_FILE environment variable is set instead')

# Mode decides DynamoDB Local vs AWS DynamoDB service
parser.add_argument(
    '--mode',
    help='Whether to connect to DynamoDB Local or AWS DynamoDB service',
    choices=['local', 'service'],
    default='service'
)

# DynamoDB endpoint hostname (without protocol or port)
parser.add_argument('--endpoint', help='DynamoDB endpoint hostname')

# Port for DynamoDB Local
parser.add_argument('--port', help='Port for DynamoDB Local (default 8000)', type=int)

# Port for Flask web server
parser.add_argument('--serverPort', help='Port for Flask server', type=int)

# Parse command line arguments
args = parser.parse_args()

# -------------------- CONFIG FILE HANDLING --------------------

configFile = args.config
config = None

# If config file path is provided via environment variable
if 'CONFIG_FILE' in os.environ:
    if configFile is not None:
        # Prevent conflict between CLI arg and env variable
        raise Exception('Cannot specify --config when setting the CONFIG_FILE environment variable')
    configFile = os.environ['CONFIG_FILE']

# Load config file if available
if configFile is not None:
    config = ConfigParser()
    config.read(configFile)

# -------------------- EC2 INSTANCE METADATA OPTION --------------------

# Determines whether to read AWS region from EC2 metadata service
use_instance_metadata = ""
if 'USE_EC2_INSTANCE_METADATA' in os.environ:
    use_instance_metadata = os.environ['USE_EC2_INSTANCE_METADATA']

# -------------------- DYNAMODB CONNECTION --------------------

# Initialize DynamoDB connection manager
cm = ConnectionManager(
    mode=args.mode,
    config=config,
    endpoint=args.endpoint,
    port=args.port,
    use_instance_metadata=use_instance_metadata
)

# Initialize game controller with DynamoDB connection
controller = GameController(cm)

# -------------------- FLASK SERVER PORT SETUP --------------------

serverPort = args.serverPort

# Read Flask-related settings from config file
if config is not None:
    if config.has_option('flask', 'secret_key'):
        application.secret_key = config.get('flask', 'secret_key')
    if serverPort is None:
        if config.has_option('flask', 'serverPort'):
            serverPort = config.get('flask', 'serverPort')

# Override port using environment variable (useful for Elastic Beanstalk)
if 'SERVER_PORT' in os.environ:
    serverPort = int(os.environ['SERVER_PORT'])

# Default Flask port if nothing specified
if serverPort is None:
    serverPort = 5000

"""
Define the urls and actions the app responds to
"""

# -------------------- LOGOUT ROUTE --------------------

@application.route('/logout')
def logout():
    # Clears the logged-in user from session
    session["username"] = None
    # Redirect user back to index page
    return redirect("/index")

# -------------------- CREATE TABLE ROUTE --------------------

@application.route('/table', methods=["GET", "POST"])
def createTable():
    # Creates the DynamoDB Games table
    cm.createGamesTable()

    # Wait until the table becomes ACTIVE
    while controller.checkIfTableIsActive() == False:
        time.sleep(3)

    # Redirect to index once table is ready
    return redirect('/index')

# -------------------- INDEX / LOGIN ROUTE --------------------

@application.route('/')
@application.route('/index', methods=["GET", "POST"])
def index():
    # Handles login and displays dashboard (invites, games, finished games)

    # If no user is logged in
    if session == {} or session.get("username", None) == None:
        form = request.form
        if form:
            formInput = form["username"]
            # Store username in session if valid
            if formInput and formInput.strip():
                session["username"] = request.form["username"]
            else:
                session["username"] = None
        else:
            session["username"] = None

    # Redirect POST requests to avoid duplicate submissions
    if request.method == "POST":
        return redirect('/index')

    # Fetch game invites for logged-in user
    inviteGames = controller.getGameInvites(session["username"])
    if inviteGames == None:
        flash("Table has not been created yet, please follow this link to create table.")
        return render_template("table.html", user="")

    # Convert invite items into Game objects
    inviteGames = [Game(inviteGame) for inviteGame in inviteGames]

    # Fetch games currently in progress
    inProgressGames = controller.getGamesWithStatus(session["username"], "IN_PROGRESS")
    inProgressGames = [Game(inProgressGame) for inProgressGame in inProgressGames]

    # Fetch finished games
    finishedGames   = controller.getGamesWithStatus(session["username"], "FINISHED")
    fs = [Game(finishedGame) for finishedGame in finishedGames]

    # Render index page with all game data
    return render_template(
        "index.html",
        user=session["username"],
        invites=inviteGames,
        inprogress=inProgressGames,
        finished=fs
    )

# -------------------- CREATE GAME PAGE --------------------

@application.route('/create')
def create():
    # Ensures user is logged in before creating a game
    if session.get("username", None) == None:
        flash("Need to login to create game")
        return redirect("/index")
    return render_template("create.html", user=session["username"])

# -------------------- CREATE GAME ACTION --------------------

@application.route('/play', methods=["POST"])
def play():
    # Handles form submission for creating a new game

    form = request.form
    if form:
        creator = session["username"]
        gameId  = str(uuid4())          # Generate unique game ID
        invitee = form["invitee"].strip()

        # Validate invitee name
        if not invitee or creator == invitee:
            flash("Use valid a name (not empty or your name)")
            return redirect("/create")

        # Create game in DynamoDB
        if controller.createNewGame(gameId, creator, invitee):
            return redirect("/game="+gameId)

    # If something fails
    flash("Something went wrong creating the game.")
    return redirect("/create")

# -------------------- GAME PAGE --------------------

@application.route('/game=<gameId>')
def game(gameId):
    # Displays the game board for a given gameId

    # Require login
    if session.get("username", None) == None:
        flash("Need to login")
        return redirect("/index")

    # Fetch game from DynamoDB
    item = controller.getGame(gameId)
    if item == None:
        flash("That game does not exist.")
        return redirect("/index")

    # Get board state
    boardState = controller.getBoardState(item)

    # Check for win/draw
    result = controller.checkForGameResult(boardState, item, session["username"])

    # If game finished, update status
    if result != None:
        if controller.changeGameToFinishedState(item, result, session["username"]) == False:
            flash("Some error occured while trying to finish game.")

    # Wrap item in Game model
    game = Game(item)
    status   = game.status
    turn     = game.turn

    # Append X or O to turn display if game not finished
    if game.getResult(session["username"]) == None:
        if (turn == game.o):
            turn += " (O)"
        else:
            turn += " (X)"

    # Prepare game data JSON for frontend
    gameData = {'gameId': gameId, 'status': game.status, 'turn': game.turn, 'board': boardState}
    gameJson = json.dumps(gameData)

    # Render play page with board positions
    return render_template(
        "play.html",
        gameId=gameId,
        gameJson=gameJson,
        user=session["username"],
        status=status,
        turn=turn,
        opponent=game.getOpposingPlayer(session["username"]),
        result=result,
        TopLeft=boardState[0],
        TopMiddle=boardState[1],
        TopRight=boardState[2],
        MiddleLeft=boardState[3],
        MiddleMiddle=boardState[4],
        MiddleRight=boardState[5],
        BottomLeft=boardState[6],
        BottomMiddle=boardState[7],
        BottomRight=boardState[8]
    )

# -------------------- GAME DATA API --------------------

@application.route('/gameData=<gameId>')
def gameData(gameId):
    # Returns JSON data for AJAX polling

    item = controller.getGame(gameId)
    boardState = controller.getBoardState(item)

    if item == None:
        return jsonify(error='That game does not exist')

    game = Game(item)
    return jsonify(
        gameId=gameId,
        status=game.status,
        turn=game.turn,
        board=boardState
    )

# -------------------- ACCEPT INVITE --------------------

@application.route('/accept=<invite>', methods=["POST"])
def accept(invite):
    # Accepts a game invite and moves game to IN_PROGRESS

    gameId = request.form["response"]
    game = controller.getGame(gameId)

    if game == None:
        flash("That game does not exist anymore.")
        redirect("/index")

    if not controller.acceptGameInvite(game):
        flash("Error validating the game...")
        redirect("/index")

    return redirect("/game="+game["GameId"])

# -------------------- REJECT INVITE --------------------

@application.route('/reject=<invite>', methods=["POST"])
def reject(invite):
    # Rejects a game invite and deletes it from DynamoDB

    gameId = request.form["response"]
    game = controller.getGame(gameId)

    if game == None:
        flash("That game doesn't exist anymore.")
        redirect("/index")

    if not controller.rejectGameInvite(game):
        flash("Something went wrong when deleting invite.")
        redirect("/index")

    return redirect("/index")

# -------------------- MAKE MOVE --------------------

@application.route('/select=<gameId>', methods=["POST"])
def selectSquare(gameId):
    # Handles a player selecting a square on the board

    value = request.form["cell"]

    item = controller.getGame(gameId)
    if item == None:
        flash("This is not a valid game.")
        return redirect("/index")

    # Attempt conditional update (turn check, empty cell, game state)
    if controller.updateBoardAndTurn(item, value, session["username"]) == False:
        flash(
            "You have selected a square either when \
                it's not your turn, \
                the square is already selected, \
                or the game is not 'In-Progress'.",
            "updateError"
        )
        return redirect("/game="+gameId)

    return redirect("/game="+gameId)

# -------------------- APP ENTRY POINT --------------------

if __name__ == "__main__":
    # Start Flask server if connection manager exists
    if cm:
        application.run(debug = True, port=serverPort, host='0.0.0.0')
