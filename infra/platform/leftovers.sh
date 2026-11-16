#!/usr/bin/env bash
# After make eks-down: lists anything from the platform stack that still exists (and would still cost money).
# Empty output under every heading = nothing left. The bootstrap (state bucket, budget, OIDC) is expected to stay.
set -uo pipefail
export AWS_REGION=${AWS_REGION:-us-east-1}
echo "== tagged with stack=platform =="
aws resourcegroupstaggingapi get-resources --tag-filters Key=stack,Values=platform \
  --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n'
echo "== EKS clusters ==";        aws eks list-clusters --query 'clusters' --output text
echo "== running EC2 instances =="; aws ec2 describe-instances --filters Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output text
echo "== NAT gateways ==";        aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId' --output text
echo "== Elastic IPs ==";         aws ec2 describe-addresses --query 'Addresses[].PublicIp' --output text
echo "== load balancers ==";      aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
echo "== EBS volumes ==";         aws ec2 describe-volumes --query 'Volumes[].[VolumeId,Size,State]' --output text
echo "== RDS instances ==";       aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text
