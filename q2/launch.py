import boto3
import time
import argparse
import sys
from botocore.exceptions import ClientError

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-name', help='EC2 Key Pair Name (optional)')
    args = parser.parse_args()

    region = 'us-west-2'
    ec2 = boto3.client('ec2', region_name=region)
    iam = boto3.client('iam', region_name=region)

    tag_name = 'Project'
    tag_value = 'ee547-hw5'
    filters = [
        {'Name': f'tag:{tag_name}', 'Values': [tag_value]},
        {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'shutting-down', 'stopping', 'stopped']}
    ]

    existing = ec2.describe_instances(Filters=filters)
    for res in existing.get('Reservations', []):
        for inst in res.get('Instances', []):
            print(f"Instance already found in non-terminated state: {inst['InstanceId']} ({inst['State']['Name']})")
            sys.exit(1)

    print("Finding the latest Ubuntu 26.04 AMI...")
    ami_resp = ec2.describe_images(
        Owners=['099720109477'],
        Filters=[{'Name': 'name', 'Values': ['ubuntu/images/hvm-ssd-gp3/ubuntu-resolute-26.04-amd64-server-*']}]
    )
    images = sorted(ami_resp['Images'], key=lambda x: x['CreationDate'], reverse=True)
    if not images:
        print("Error: Could not find AMI.")
        sys.exit(1)
    ami_id = images[0]['ImageId']
    print(f"Using AMI: {ami_id}")

    print("Ensuring instance profile exists...")
    iam.get_waiter('instance_profile_exists').wait(InstanceProfileName='ee547-hw5-role')

    with open('user-data.sh', 'r') as f:
        user_data = f.read()

    run_params = {
        'ImageId': ami_id,
        'InstanceType': 't3.micro',
        'SecurityGroups': ['ee547-hw5-sg'],
        'IamInstanceProfile': {'Name': 'ee547-hw5-role'},
        'UserData': user_data,
        'TagSpecifications': [{'ResourceType': 'instance', 'Tags': [{'Key': tag_name, 'Value': tag_value}]}],
        'MetadataOptions': {'HttpTokens': 'required', 'HttpPutResponseHopLimit': 2},
        'MinCount': 1,
        'MaxCount': 1
    }
    if args.key_name:
        run_params['KeyName'] = args.key_name

    print("Launching instance...")
    instance = None
    for attempt in range(12): # 12 attempts * 5 sec = 60 seconds
        try:
            resp = ec2.run_instances(**run_params)
            instance = resp['Instances'][0]
            break
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidParameterValue' and 'profile' in e.response['Error']['Message'].lower():
                print("IAM profile not fully propagated yet, waiting 5 seconds...")
                time.sleep(5)
            else:
                raise

    if not instance:
        print("Failed to launch instance due to IAM propagation timeout.")
        sys.exit(1)

    instance_id = instance['InstanceId']
    print(f"Instance {instance_id} launched. Waiting for 'running' state...")

    ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])

    instance_info = ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
    public_ip = instance_info.get('PublicIpAddress', 'None')

    print("====================================")
    print(f"Launch Successful!")
    print(f"Instance ID: {instance_id}")
    print(f"Public IP:   {public_ip}")
    print("====================================")
    print("Wait 3-5 minutes for user-data.sh to install Docker and start the API.")

if __name__ == "__main__":
    main()
