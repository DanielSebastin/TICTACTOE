# Raised when AWS returns an error JSON response
from boto.exception         import JSONResponseError

# Raised when a conditional write fails in DynamoDB
from boto.dynamodb2.exceptions import ConditionalCheckFailedException

# Raised when an item is not found in DynamoDB
from boto.dynamodb2.exceptions import ItemNotFound

# Raised when query parameters are invalid
from boto.dynamodb2.exceptions import ValidationException

# Represents a DynamoDB item
from boto.dynamodb2.items   import Item

# Represents a DynamoDB table
from boto.dynamodb2.table   import Table

# Used to generate timestamps for game status
from datetime               import datetime


class GameController:
    """
    This GameController class basically acts as a singleton providing the necessary
    DynamoDB API calls.
    """

    def __init__(self, connectionManager):
        # Store reference to ConnectionManager (holds DynamoDB connection)
        self.cm = connectionManager

        # Error code used to detect missing DynamoDB resources
        self.ResourceNotFound = 'com.amazonaws.dynamodb.v20120810#ResourceNotFoundException'

    def createNewGame(self, gameId, creator, invitee):
        """
        Creates a new game item in the Games table using the high-level API.
        Initializes all required attributes needed to track game state.
        Returns True/False depending on whether the save succeeds.
        """

        # Current timestamp
        now = str(datetime.now())

        # Initial status of a new game
        statusDate = "PENDING_" + now

        # Create DynamoDB item with required attributes
        item = Item(self.cm.getGamesTable(), data={
                            "GameId"     : gameId,
                            "HostId"     : creator,
                            "StatusDate" : statusDate,
                            "OUser"      : creator,
                            "Turn"       : invitee,
                            "OpponentId" : invitee
                        })

        # Save item to DynamoDB
        return item.save()

    def checkIfTableIsActive(self):
        # Describe the Games table
        description = self.cm.db.describe_table("Games")

        # Read table status
        status = description['Table']['TableStatus']

        # Return True only if table is ACTIVE
        return status == "ACTIVE"

    def getGame(self, gameId):
        """
        Retrieves a game item from the Games table using GameId as primary key.
        Returns None if the item does not exist or an error occurs.
        """
        try:
            item = self.cm.getGamesTable().get_item(GameId=gameId)
        except ItemNotFound as inf:
            return None
        except JSONResponseError as jre:
            return None

        return item

    def acceptGameInvite(self, game):
        # Generate timestamp
        date = str(datetime.now())

        # Update status to IN_PROGRESS
        status = "IN_PROGRESS_"
        statusDate = status + date

        # Primary key of the item to update
        key = {
                "GameId" : { "S" : game["GameId"] }
            }

        # Attribute update to change StatusDate
        attributeUpdates = {
                        "StatusDate" : {
                            "Action" : "PUT",
                            "Value"  : { "S" : statusDate }
                            }
                        }

        # Ensure the game is still pending before accepting
        expectations = {"StatusDate" : {
                            "AttributeValueList": [{"S" : "PENDING_"}],
                            "ComparisonOperator": "BEGINS_WITH"}
                    }

        # Conditional update using low-level API
        try:
            self.cm.db.update_item(
                "Games",
                key=key,
                attribute_updates=attributeUpdates,
                expected=expectations
            )
        except ConditionalCheckFailedException as ccfe:
            return False

        return True

    def rejectGameInvite(self, game):
        """
        Deletes a pending game invite from the table.
        Only succeeds if the game is still in PENDING state.
        """

        # Primary key of the item
        key = {
                "GameId": { "S" : game["GameId"] }
            }

        # Ensure the game is still pending
        expectation = {"StatusDate" : {
                            "AttributeValueList": [{"S" : "PENDING_"}],
                            "ComparisonOperator": "BEGINS_WITH" }
                    }

        # Conditional delete
        try:
            self.cm.db.delete_item("Games", key, expected=expectation)
        except Exception as e:
            return False

        return True

    def getGameInvites(self, user):
        """
        Queries the OpponentId-StatusDate index to fetch up to
        10 pending game invites for a user.
        """
        invites = []

        # If user not logged in, return empty list
        if user == None:
            return invites

        # Query GSI for pending invites
        gameInvitesIndex = self.cm.getGamesTable().query(
            OpponentId__eq=user,
            StatusDate__beginswith="PENDING_",
            index="OpponentId-StatusDate-index",
            limit=10
        )

        # Iterate through query results
        for i in range(10):
            try:
                gameInvite = next(gameInvitesIndex)
            except StopIteration as si:
                break
            except ValidationException as ve:
                break
            except JSONResponseError as jre:
                if jre.body.get(u'__type', None) == self.ResourceNotFound:
                    return None
                else:
                    raise jre

            invites.append(gameInvite)

        return invites

    def updateBoardAndTurn(self, item, position, current_player):
       """
        Using the Low Level API, we execute a conditional write on the Item.
        We are able to specify the particular item by passing in the keys param, in
        this case it's just a GameId.
        In expectations, we expect
            the StatusDate to be IN_PROGRESS_<date of the game>,
            the Turn to be the player who is currently logged in,
            the "Space" to not exist as an attribute because it hasn't been written to yet.
        If this succeeds we update the Turn to the next player, as well.
        Returns True/False depending on the success of the these operations.
        """

        # Identify players
        player_one = item["HostId"]
        player_two = item["OpponentId"]
        gameId     = item["GameId"]

        # Extract date portion from StatusDate
        statusDate = item["StatusDate"]
        date = statusDate.split("_")[1]

        # Default marker
        representation = "X"

        # Assign O if current player is OUser
        if item["OUser"] == current_player:
            representation = "O"

        # Determine next player's turn
        if current_player == player_one:
            next_player = player_two
        else:
            next_player = player_one

        # Primary key
        key = {
                "GameId" : { "S" : gameId }
            }

        # Attribute updates for board position and turn
        attributeUpdates = {
                        position : {
                            "Action" : "PUT",
                            "Value"  : { "S" : representation }
                            },
                        "Turn" : {
                            "Action" : "PUT",
                            "Value" : { "S" : next_player }
                            }
                        }

        # Conditions that must be satisfied
        expectations = {
            "StatusDate" : {
                "AttributeValueList": [{"S" : "IN_PROGRESS_"}],
                "ComparisonOperator": "BEGINS_WITH"
            },
            "Turn"       : {"Value" : {"S" : current_player}},
            position     : {"Exists" : False}
        }

        # Conditional update
        try:
            self.cm.db.update_item(
                "Games",
                key=key,
                attribute_updates=attributeUpdates,
                expected=expectations
            )
        except ConditionalCheckFailedException as ccfe:
            return False

        return True

    def getBoardState(self, item):
        """
        Converts board attributes into a 9-element list.
        Empty squares are represented by a blank space.
        """

        squares = [
            "TopLeft", "TopMiddle", "TopRight",
            "MiddleLeft", "MiddleMiddle", "MiddleRight",
            "BottomLeft", "BottomMiddle", "BottomRight"
        ]

        state = []
        for square in squares:
            value = item[square]
            if value == None:
                state.append(" ")
            else:
                state.append(value)

        return state

    def checkForGameResult(self, board, item, current_player):
        """
        Evaluates the board to determine Win, Lose, Tie, or None.
        """

        yourMarker = "X"
        theirMarker = "O"

        if current_player == item["OUser"]:
            yourMarker = "O"
            theirMakrer = "X"

        # All possible winning index combinations
        winConditions = [
            [0,3,6],[0,1,2],[0,4,8],
            [1,4,7],[2,5,8],[2,4,6],
            [3,4,5],[6,7,8]
        ]

        for winCondition in winConditions:
            b_zero = board[winCondition[0]]
            b_one  = board[winCondition[1]]
            b_two  = board[winCondition[2]]

            if b_zero == b_one and b_one == b_two and b_two == yourMarker:
                return "Win"

            if b_zero == b_one and b_one == b_two and b_two == theirMarker:
                return "Lose"

        # Check for tie
        if self.checkForTie(board):
            return "Tie"

        return None

    def checkForTie(self, board):
        """
        Returns True if there are no empty spaces left on the board.
        """

        for cell in board:
            if cell == " ":
                return False
        return True

    def changeGameToFinishedState(self, item, result, current_user):
        """
        Finalizes a game by setting FINISHED status and storing the result.
        """

        # If game already finished
        if item["Result"] != None:
            return True

        # Update status and turn
        date = str(datetime.now())
        status = "FINISHED"
        item["StatusDate"] = status + "_" + date
        item["Turn"] = "N/A"

        # Store result
        if result == "Tie":
            item["Result"] = result
        elif result == "Win":
            item["Result"] = current_user
        else:
            if item["HostId"] == current_user:
                item["Result"] = item["OpponentId"]
            else:
                item["Result"] = item["HostId"]

        return item.save()

    def mergeQueries(self, host, opp, limit=10):
        """
        Merges two sorted iterators (host games and opponent games)
        into a single list of most recent games.
        """

        games = []
        game_one = None
        game_two = None

        while len(games) <= limit:
            if game_one == None:
                try:
                    game_one = next(host)
                except StopIteration as si:
                    if game_two != None:
                        games.append(game_two)

                    for rest in opp:
                        if len(games) == limit:
                            break
                        else:
                            games.append(rest)
                    return games

            if game_two == None:
                try:
                    game_two = next(opp)
                except StopIteration as si:
                    if game_one != None:
                        games.append(game_one)

                    for rest in host:
                        if len(games) == limit:
                            break
                        else:
                            games.append(rest)
                    return games

            if game_one > game_two:
                games.append(game_one)
                game_one = None
            else:
                games.append(game_two)
                game_two = None

        return games

    def getGamesWithStatus(self, user, status):
        """
        Fetches games where the user is either host or opponent
        and the game has the specified status.
        """

        if user == None:
            return []

        # Query games where user is host
        hostGamesInProgress = self.cm.getGamesTable().query(
            HostId__eq=user,
            StatusDate__beginswith=status,
            index="HostId-StatusDate-index",
            limit=10
        )

        # Query games where user is opponent
        oppGamesInProgress = self.cm.getGamesTable().query(
            OpponentId__eq=user,
            StatusDate__beginswith=status,
            index="OpponentId-StatusDate-index",
            limit=10
        )

        # Merge and return most recent games
        games = self.mergeQueries(hostGamesInProgress, oppGamesInProgress)
        return games
