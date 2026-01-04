from boto.exception import JSONResponseError
from boto.dynamodb2.exceptions import ConditionalCheckFailedException
from boto.dynamodb2.exceptions import ItemNotFound
from boto.dynamodb2.exceptions import ValidationException
from boto.dynamodb2.items import Item
from boto.dynamodb2.table import Table
from datetime import datetime


class GameController:
    """
    This GameController class acts as a singleton
    providing all DynamoDB API calls for the game.
    """

    def __init__(self, connectionManager):
        self.cm = connectionManager
        self.ResourceNotFound = 'com.amazonaws.dynamodb.v20120810#ResourceNotFoundException'

    def createNewGame(self, gameId, creator, invitee):
        now = str(datetime.now())
        statusDate = "PENDING_" + now

        item = Item(self.cm.getGamesTable(), data={
            "GameId": gameId,
            "HostId": creator,
            "StatusDate": statusDate,
            "OUser": creator,
            "Turn": invitee,
            "OpponentId": invitee
        })

        return item.save()

    def checkIfTableIsActive(self):
        description = self.cm.db.describe_table("Games")
        status = description['Table']['TableStatus']
        return status == "ACTIVE"

    def getGame(self, gameId):
        try:
            return self.cm.getGamesTable().get_item(GameId=gameId)
        except (ItemNotFound, JSONResponseError):
            return None

    def acceptGameInvite(self, game):
        date = str(datetime.now())
        statusDate = "IN_PROGRESS_" + date

        key = {
            "GameId": {"S": game["GameId"]}
        }

        attributeUpdates = {
            "StatusDate": {
                "Action": "PUT",
                "Value": {"S": statusDate}
            }
        }

        expectations = {
            "StatusDate": {
                "AttributeValueList": [{"S": "PENDING_"}],
                "ComparisonOperator": "BEGINS_WITH"
            }
        }

        try:
            self.cm.db.update_item(
                "Games",
                key=key,
                attribute_updates=attributeUpdates,
                expected=expectations
            )
        except ConditionalCheckFailedException:
            return False

        return True

    def rejectGameInvite(self, game):
        key = {
            "GameId": {"S": game["GameId"]}
        }

        expectation = {
            "StatusDate": {
                "AttributeValueList": [{"S": "PENDING_"}],
                "ComparisonOperator": "BEGINS_WITH"
            }
        }

        try:
            self.cm.db.delete_item("Games", key, expected=expectation)
        except Exception:
            return False

        return True

    def getGameInvites(self, user):
        invites = []
        if user is None:
            return invites

        index = self.cm.getGamesTable().query(
            OpponentId__eq=user,
            StatusDate__beginswith="PENDING_",
            index="OpponentId-StatusDate-index",
            limit=10
        )

        for _ in range(10):
            try:
                invites.append(next(index))
            except (StopIteration, ValidationException):
                break
            except JSONResponseError as jre:
                if jre.body.get('__type') == self.ResourceNotFound:
                    return None
                raise jre

        return invites

    def updateBoardAndTurn(self, item, position, current_player):
        """
        Performs a conditional update on the board and turn.
        Prevents invalid moves and cheating.
        """

        player_one = item["HostId"]
        player_two = item["OpponentId"]
        gameId = item["GameId"]

        representation = "O" if item["OUser"] == current_player else "X"
        next_player = player_two if current_player == player_one else player_one

        key = {
            "GameId": {"S": gameId}
        }

        attributeUpdates = {
            position: {
                "Action": "PUT",
                "Value": {"S": representation}
            },
            "Turn": {
                "Action": "PUT",
                "Value": {"S": next_player}
            }
        }

        expectations = {
            "StatusDate": {
                "AttributeValueList": [{"S": "IN_PROGRESS_"}],
                "ComparisonOperator": "BEGINS_WITH"
            },
            "Turn": {"Value": {"S": current_player}},
            position: {"Exists": False}
        }

        try:
            self.cm.db.update_item(
                "Games",
                key=key,
                attribute_updates=attributeUpdates,
                expected=expectations
            )
        except ConditionalCheckFailedException:
            return False

        return True

    def getBoardState(self, item):
        squares = [
            "TopLeft", "TopMiddle", "TopRight",
            "MiddleLeft", "MiddleMiddle", "MiddleRight",
            "BottomLeft", "BottomMiddle", "BottomRight"
        ]

        return [item[s] if item[s] is not None else " " for s in squares]

    def checkForGameResult(self, board, item, current_player):
        yourMarker = "O" if current_player == item["OUser"] else "X"
        theirMarker = "X" if yourMarker == "O" else "O"

        winConditions = [
            [0,3,6],[0,1,2],[0,4,8],
            [1,4,7],[2,5,8],[2,4,6],
            [3,4,5],[6,7,8]
        ]

        for w in winConditions:
            if board[w[0]] == board[w[1]] == board[w[2]] == yourMarker:
                return "Win"
            if board[w[0]] == board[w[1]] == board[w[2]] == theirMarker:
                return "Lose"

        if " " not in board:
            return "Tie"

        return None

    def changeGameToFinishedState(self, item, result, current_user):
        if item["Result"] is not None:
            return True

        date = str(datetime.now())
        item["StatusDate"] = "FINISHED_" + date
        item["Turn"] = "N/A"

        if result == "Tie":
            item["Result"] = "Tie"
        elif result == "Win":
            item["Result"] = current_user
        else:
            item["Result"] = (
                item["OpponentId"]
                if item["HostId"] == current_user
                else item["HostId"]
            )

        return item.save()

    def getGamesWithStatus(self, user, status):
        if user is None:
            return []

        hostGames = self.cm.getGamesTable().query(
            HostId__eq=user,
            StatusDate__beginswith=status,
            index="HostId-StatusDate-index",
            limit=10
        )

        oppGames = self.cm.getGamesTable().query(
            OpponentId__eq=user,
            StatusDate__beginswith=status,
            index="OpponentId-StatusDate-index",
            limit=10
        )

        games = list(hostGames) + list(oppGames)
        games.sort(reverse=True)
        return games[:10]
