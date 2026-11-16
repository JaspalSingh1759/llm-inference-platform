# Network: 2 availability zones, public subnets (NAT gateway, future load balancers) and private subnets
# (nodes, RDS). Nodes have no public IPs; they reach the internet through one NAT gateway.
locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = var.name
  cidr = "10.20.0.0/16"
  azs  = local.azs

  public_subnets  = ["10.20.0.0/24", "10.20.1.0/24"]
  private_subnets = ["10.20.16.0/20", "10.20.32.0/20"] # big: the VPC CNI gives every pod a VPC IP

  # One NAT gateway for both zones: cheaper ($0.045/h instead of $0.09/h), but a zone outage cuts the
  # other zone's internet access. Production: one per zone.
  enable_nat_gateway = true
  single_nat_gateway = true

  # Tags that let Kubernetes find the subnets for load balancers (P5 onwards).
  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}
