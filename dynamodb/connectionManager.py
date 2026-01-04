# Imports helper functions to connect to DynamoDB and create the Games table
from .setupDynamoDB          import getDynamoDBConnection, createGamesTable

# Represents a DynamoDB table object
from boto.dynamodb2.table   import Table

# Used to generate unique identifiers (not used directly here but imported for consistency)
from uuid                   import uuid4


class ConnectionManager:
    # This class manages the DynamoDB connection and the Games table reference

    def __init__(self, mode=None, config=None, endpoint=None, port=None, use_instance_metadata=False):
        # Holds the DynamoDB connection object
        self.db = None

        # Holds the DynamoDB Games table object
        self.gamesTable = None

        # If running in local mode (DynamoDB Local)
        if mode == "local":
            # Local mode should not use config files
            if config is not None:
                raise Exception('Cannot specify config when in local mode')

            # Default endpoint for DynamoDB Local
            if endpoint is None:
                endpoint = 'localhost'

            # Default port for DynamoDB Local
            if port is None:
                port = 8000

            # Create DynamoDB Local connection
            self.db = getDynamoDBConnection(endpoint=endpoint, port=port, local=True)

        # If running against AWS DynamoDB service
        elif mode == "service":
            # Create DynamoDB connection using AWS credentials / metadata
            self.db = getDynamoDBConnection(
                config=config,
                endpoint=endpoint,
                use_instance_metadata=use_instance_metadata
            )

        # Invalid mode provided
        else:
            raise Exception("Invalid arguments, please refer to usage.");

        # Initialize Games table reference
        self.setupGamesTable()

    def setupGamesTable(self):
        # Attempts to load the existing Games table
        try:
            self.gamesTable = Table("Games", connection=self.db)
        except Exception as e:
            # Raised if the table does not exist or connection fails
            raise e("There was an issue trying to retrieve the Games table.")

    def getGamesTable(self):
        # Returns the Games table object
        # Re-initializes it if not already loaded
        if self.gamesTable == None:
            self.setupGamesTable()
        return self.gamesTable

    def createGamesTable(self):
        # Creates the Games table in DynamoDB
        self.gamesTable = createGamesTable(self.db)
