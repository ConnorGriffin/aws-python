import boto3
from datetime import datetime, timedelta
import time

def lambda_handler(event, context):
    # Define our tag-getting function
    def getTagValue(tagSet, key):
        for tag in tagSet:
            if tag['Key'] == key:
                return tag['Value']

    # Get the current time in a (potentially) ISO 8601 compliant format
    now = datetime.now()
    isoDateTime = now.strftime('%Y-%m-%dT%H%M%S')


    # Define the snapshot-eligible filter
    eligibleFilter = [
        {'Name': 'instance-state-name', 'Values': ['running']},
        {'Name': 'tag:AutoSnapshot', 'Values': ['Enabled']}
    ]

    # Set the timeout (seconds), used when checking for AMI availability
    timeout = 60

    # Initiate the client
    ec2 = boto3.client('ec2')

    # List all EC2 regions
    regions = ec2.describe_regions().get('Regions',[])

    # Loop through each region
    for region in regions:

        # Connect to the region
        ec2 = boto3.client('ec2', region_name=region['RegionName'])

        # Get all running reservations matching the filter
        reservations = ec2.describe_instances(Filters=eligibleFilter)['Reservations']

        # Get instances from reservations list using a sum and list comprehension (https://docs.python.org/2/tutorial/datastructures.html#list-comprehensions)
        instances = sum(
            [
                [i for i in r['Instances']]
                for r in reservations
            ], [])

        # Iterate through instances in each launch group
        for instance in instances:

            # Check for AMIs created within the last 24 hours, don't run if any exist
            # Potentially vary this based on some kind of retention tag

            # Get the tag values
            nameTag = getTagValue(instance['Tags'],'Name')
            serviceIdTag = getTagValue(instance['Tags'],'Service ID')
            environmentTag = getTagValue(instance['Tags'],'Environment')
            ownerTag = getTagValue(instance['Tags'],'Owner')
            snapshotRetentionTag = getTagValue(instance['Tags'],'AutoSnapshotRetention')

            # Convert the snapshotRetention tag to a DeleteAfter date
            deleteAfter = (now + timedelta(days=int(snapshotRetentionTag))).isoformat()

            # Define the tags to attach to the AMI and underlying volumes
            amiTags = [
                {'Key': 'Name', 'Value': nameTag},
                {'Key': 'Service ID', 'Value': serviceIdTag},
                {'Key': 'Environment', 'Value': environmentTag},
                {'Key': 'Owner', 'Value': ownerTag},
                {'Key': 'SourceInstance', 'Value': instance['InstanceId']},
                {'Key': 'DeleteAfter', 'Value': deleteAfter}
            ]

            # Define the create_image parameters
            imageParams = {
                'InstanceId': instance['InstanceId'],
                'Name': '%s AMI %s' % (nameTag,isoDateTime),
                'Description': '%s AMI created by Lambda Snapshot Automation' % (nameTag),
                'NoReboot': True
            }

            # Create the AMI
            amiResult = ec2.create_image(**imageParams)

            # Loop until the AMI is available for tagging
            timeoutStart = time.time()
            while time.time() < timeoutStart + timeout:
                image = ec2.describe_images(ImageIds=[amiResult['ImageId']]).get('Images',[])[0]
                if image:
                    break
                else:
                    time.sleep(1)

            # Add the tags to the AMI
            ec2.create_tags(Resources=[image['ImageId']],Tags=amiTags)

            # List the underlying snapshots and tag those as well
