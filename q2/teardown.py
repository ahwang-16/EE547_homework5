import boto3
import argparse
from botocore.exceptions import ClientError

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true', help='Delete all resources created by setup.py')
    args = parser.parse_args()

    region = 'us-west-2'
    ec2 = boto3.client('ec2', region_name=region)
    iam = boto3.client('iam', region_name=region)
    ssm = boto3.client('ssm', region_name=region)
    ecr = boto3.client('ecr', region_name=region)

    matched = False

    instances = ec2.describe_instances(Filters=[{'Name': 'tag:Project', 'Values': ['ee547-hw5']}])
    instance_ids = [inst['InstanceId'] for res in instances.get('Reservations', []) for inst in res.get('Instances', []) if inst['State']['Name'] not in ['terminated', 'shutting-down']]

    if instance_ids:
        matched = True
        print(f"Terminating instances: {instance_ids}")
        ec2.terminate_instances(InstanceIds=instance_ids)
        print("Waiting for termination to complete (required before deleting Security Group)...")
        ec2.get_waiter('instance_terminated').wait(InstanceIds=instance_ids)
        print("Instances terminated.")

    if not args.all:
        if not matched:
            print("No tagged instances matched. Nothing to do.")
        return

    try:
        ec2.delete_security_group(GroupName='ee547-hw5-sg')
        print("Deleted Security Group: ee547-hw5-sg")
        matched = True
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            pass
        else:
            raise

    try:
        iam.remove_role_from_instance_profile(InstanceProfileName='ee547-hw5-role', RoleName='ee547-hw5-role')
        iam.delete_instance_profile(InstanceProfileName='ee547-hw5-role')
        print("Deleted Instance Profile: ee547-hw5-role")
        matched = True
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            pass
        else:
            raise

    try:
        iam.delete_role_policy(RoleName='ee547-hw5-role', PolicyName='ee547-hw5-policy')
        iam.delete_role(RoleName='ee547-hw5-role')
        print("Deleted IAM Role and Inline Policy: ee547-hw5-role")
        matched = True
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            pass
        else:
            raise

    try:
        ssm.delete_parameter(Name='/ee547/hw5/jwt-secret')
        print("Deleted SSM Parameter: /ee547/hw5/jwt-secret")
        matched = True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            pass
        else:
            raise

    try:
        ecr.delete_repository(repositoryName='ee547-hw5-api', force=True)
        print("Deleted ECR Repository: ee547-hw5-api")
        matched = True
    except ClientError as e:
        if e.response['Error']['Code'] == 'RepositoryNotFoundException':
            pass
        else:
            raise

    if not matched:
        print("Nothing matched. No resources found to delete.")

if __name__ == "__main__":
    main()
