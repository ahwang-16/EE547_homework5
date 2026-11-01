exec > >(tee /var/log/user-data.log) 2>&1
set -e

echo 'DPkg::Lock::Timeout "300";' > /etc/apt/apt.conf.d/99-lock-timeout
apt-get update

apt-get install -y ca-certificates curl unzip
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io

curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp/tmp/aws/install
/tmp/tmp/aws/install/install

usermod -aG docker ubuntu
systemctl enable --now docker

apt-get install -y python3 python3-venv

REGION="us-west-2"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region $REGION)
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY
docker pull $REGISTRY/ee547-hw5-api:latest

JWT_SECRET=$(aws ssm get-parameter --name /ee547/hw5/jwt-secret --with-decryption --query Parameter.Value --output text --region $REGION)

docker run -d --name ee547-hw5-api \
    -p 8080:8080 \
    --restart unless-stopped \
    -e AWS_REGION=$REGION \
    -e DYNAMODB_TABLE="arxiv-papers" \
    -e JWT_SECRET="$JWT_SECRET" \
    $REGISTRY/ee547-hw5-api:latest

echo "COMPLETED SETUP: API container launched successfully"
