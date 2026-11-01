import boto3
import json
import secrets
from botocore.exceptions import ClientError

def main():
    region = 'us-west-2'
    sts = boto3.client('sts', region_name=region)
    account_id = sts.get_caller_identity()['Account']

    ecr = boto3.client('ecr', region_name=region)
    ssm = boto3.client('ssm', region_name=region)
    iam = boto3.client('iam', region_name=region)
    ec2 = boto3.client('ec2', region_name=region)

    print(f"Using Account: {account_id} | Region: {region}")

    repo_name = 'ee547-hw5-api'
    try:
        ecr.describe_repositories(repositoryNames=[repo_name])
        print(f"[ECR] Repository '{repo_name}' already exists.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'RepositoryNotFoundException':
            ecr.create_repository(repositoryName=repo_name)
            print(f"[ECR] Created repository '{repo_name}'.")
        else:
            raise

    param_name = '/ee547/hw5/jwt-secret'
    try:
        ssm.get_parameter(Name=param_name)
        print(f"[SSM] Parameter '{param_name}' already exists. Skipping to avoid invalidating tokens.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            key = secrets.token_hex(32)
            ssm.put_parameter(Name=param_name, Value=key, Type='SecureString')
            print(f"[SSM] Created parameter '{param_name}'.")
        else:
            raise

    role_name = 'ee547-hw5-role'
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Action": "sts:AssumeRole", "Principal": {"Service": "ec2.amazonaws.com"}, "Effect": "Allow"}]
    }

    try:
        iam.get_role(RoleName=role_name)
        print(f"[IAM] Role '{role_name}' already exists.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=json.dumps(assume_role_policy))
            print(f"[IAM] Created role '{role_name}'.")
        else:
            raise

    policy_name = 'ee547-hw5-policy'
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["dynamodb:Query", "dynamodb:GetItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{region}:{account_id}:table/arxiv-papers",
                    f"arn:aws:dynamodb:{region}:{account_id}:table/arxiv-papers/index/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": "ssm:GetParameter",
                "Resource": f"arn:aws:ssm:{region}:{account_id}:parameter{param_name}"
            },
            {
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": f"arn:aws:ecr:{region}:{account_id}:repository/{repo_name}"
            }
        ]
    }
    iam.put_role_policy(RoleName=role_name, PolicyName=policy_name, PolicyDocument=json.dumps(policy_doc))
    print(f"[IAM] Attached inline policy '{policy_name}' to role '{role_name}'.")

    try:
        iam.get_instance_profile(InstanceProfileName=role_name)
        print(f"[IAM] Instance profile '{role_name}' already exists.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            iam.create_instance_profile(InstanceProfileName=role_name)
            iam.add_role_to_instance_profile(InstanceProfileName=role_name, RoleName=role_name)
            print(f"[IAM] Created instance profile '{role_name}'.")
        else:
            raise

    sg_name = 'ee547-hw5-sg'
    try:
        ec2.describe_security_groups(GroupNames=[sg_name])
        print(f"[EC2] Security group '{sg_name}' already exists.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            vpc_id = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])['Vpcs'][0]['VpcId']
            res = ec2.create_security_group(GroupName=sg_name, Description='HW5 API Security Group', VpcId=vpc_id)
            sg_id = res['GroupId']

            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {'IpProtocol': 'tcp', 'FromPort': 8080, 'ToPort': 8080, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ]
            )
            print(f"[EC2] Created security group '{sg_name}'.")
        else:
            raise

if __name__ == "__main__":
    main()
