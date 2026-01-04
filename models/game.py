# Item class used to represent a DynamoDB item
from boto.dynamodb2.items import Item

# Used for parsing and formatting date-time values
from datetime             import datetime

class Game:
    """
    This Game class acts as a wrapper on top of an item in the Games table.
    Each of the fields in the table is of a String type.
    GameId is the primary key.
    HostId-StatusDate, Opponent-StatusDate are Global Secondary Indexes that are Hash-Range Keys.
    The other attributes are used to maintain game state.
    """

    def __init__(self, item):
        # Store the raw DynamoDB item
        self.item = item

        # Unique identifier for the game
        self.gameId       = item["GameId"]

        # Username of the game creator
        self.hostId       = item["HostId"]

        # Username of the invited opponent
        self.opponent     = item["OpponentId"]

        # StatusDate is stored as "STATUS_DATE" or "STATUS_EXTRA_DATE"
        # Splitting allows extracting status and timestamp separately
        self.statusDate   = item["StatusDate"].split("_")

        # Player assigned the 'O' symbol
        self.o            = item["OUser"]

        # Username of the player whose turn it is
        self.turn         = item["Turn"]

    def getStatus(self):
        # Extract game status from StatusDate
        status = self.statusDate[0]

        # Handle compound status values (e.g., IN_PROGRESS)
        if len(self.statusDate) > 2:
            status += "_" + self.statusDate[1]

        return status

    # Expose status as a read-only property
    status = property(getStatus)

    def getDate(self):
        # Determine index where date starts in StatusDate
        index = 1
        if len(self.statusDate) > 2:
            index = 2

        # Convert stored string date to datetime object
        date = datetime.strptime(self.statusDate[index],'%Y-%m-%d %H:%M:%S.%f')

        # Return formatted date string
        return datetime.strftime(date, '%Y-%m-%d %H:%M:%S')

    # Expose date as a read-only property
    date = property(getDate)

    def __cmp__(self, otherGame):
        # Compare games based on timestamp for sorting
        if otherGame == None:
            return cmp(self.statusDate[1], None)
        return cmp(self.statusDate[1], otherGame.statusDate[1])

    def getOpposingPlayer(self, current_player):
        # Return the other player in the game
        if current_player == self.hostId:
            return self.opponent
        else:
            return self.hostId

    def getResult(self, current_player):
        # If game result not decided yet
        if self.item["Result"] == None:
            return None

        # Handle tie condition
        if self.item["Result"] == "Tie":
            return "Tie"

        # Determine win or loss for the current player
        if self.item["Result"] == current_player:
            return "Win"
        else:
            return "Lose"
