# Raised when AWS returns an error response in JSON format
from boto.exception import JSONResponseError

# DynamoDB index and key definitions
from boto.dynamodb2.fields import KeysOnlyIndex, GlobalAllIndex, HashKey, RangeKey

# Low-level DynamoDB connection class
from boto.dynamodb2.layer1 import DynamoDBConnection

# High-level DynamoDB table abstraction
from boto.dynamodb2.table import Table

# Python 3 URL opener
try:
    from urllib.request import urlopen
# Python 2 fallback
except ImportError:
    from urllib2 import urlopen

# Used to parse JSON responses from EC2 metadata service
import json


def getDynamoDBConnection(config=None, endpoint=None, port=None, local=False, use_instance_metadata=False):
    # Parameters dictionary passed to DynamoDBConnection
    params = {
        'is_secure': True
    }

    # ---------------- CONFIG FILE HANDLING ----------------

    # Read DynamoDB configuration from config file if provided
    if config is not None:
        if config.has_option('dynamodb', 'region'):
            params['region'] = config.get('dynamodb', 'region')
        if config.has_option('dynamodb', 'endpoint'):
            params['host'] = config.get('dynamodb', 'endpoint')

    # ---------------- COMMAND LINE ENDPOINT OVERRIDE ----------------

    # If endpoint is explicitly provided, override config values
    if endpoint is not None:
        params['host'] = endpoint
        if 'region' in params:
            del params['region']

    # ---------------- EC2 INSTANCE METADATA ----------------

    # Auto-detect region using EC2 metadata if enabled and no host is set
    if 'host' not in params and use_instance_metadata:
        response = urlopen('http://169.254.169.254/latest/dynamic/instance-identity/document').read()
        doc = json.loads(response)
        params['host'] = 'dynamodb.%s.amazonaws.com' % (doc['region'])
        if 'region' in params:
            del params['region']

    # ---------------- CREATE CONNECTION ----------------

    # Create and return DynamoDB connection
    db = DynamoDBConnection(**params)
    return db


def createGamesTable(db):
    try:
        # Global Secondary Index for querying games by HostId and StatusDate
        hostStatusDate = GlobalAllIndex(
            "HostId-StatusDate-index",
            parts=[HashKey("HostId"), RangeKey("StatusDate")],
            throughput={
                'read': 1,
                'write': 1
            }
        )

        # Global Secondary Index for querying games by OpponentId and StatusDate
        opponentStatusDate = GlobalAllIndex(
            "OpponentId-StatusDate-index",
            parts=[HashKey("OpponentId"), RangeKey("StatusDate")],
            throughput={
                'read': 1,
                'write': 1
            }
        )

        # List of all Global Secondary Indexes
        GSI = [hostStatusDate, opponentStatusDate]

        # Create the Games table with GameId as primary key
        # Uses IAM role credentials implicitly
        gamesTable = Table.create(
            "Games",
            schema=[HashKey("GameId")],
            throughput={
                'read': 1,
                'write': 1
            },
            global_indexes=GSI,
            connection=db
        )

    # If table already exists or AWS returns an error
    except JSONResponseError as jre:
        try:
            # Attempt to load the existing Games table
            gamesTable = Table("Games", connection=db)
        except Exception as e:
            # Table does not exist and could not be created
            print("Games Table doesn't exist.")

    # Always return the table reference (created or existing)
    finally:
        return gamesTable
