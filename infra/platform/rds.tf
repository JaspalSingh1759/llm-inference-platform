# RDS PostgreSQL: MLflow's database on EKS (the postgres pod in P2). Private subnets, reachable only from
# the cluster's nodes, encrypted, password generated and kept in Secrets Manager by RDS itself.

resource "aws_db_subnet_group" "mlflow" {
  count      = var.mlflow_db_enabled ? 1 : 0
  name       = "${var.name}-mlflow"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "mlflow_db" {
  count       = var.mlflow_db_enabled ? 1 : 0
  name        = "${var.name}-mlflow-db"
  description = "PostgreSQL from EKS nodes only"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "mlflow_db_from_nodes" {
  count                        = var.mlflow_db_enabled ? 1 : 0
  security_group_id            = aws_security_group.mlflow_db[0].id
  referenced_security_group_id = module.eks.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_instance" "mlflow" {
  count          = var.mlflow_db_enabled ? 1 : 0
  identifier     = "${var.name}-mlflow"
  engine         = "postgres"
  engine_version = "16" # major version only: RDS applies minor versions in the maintenance window
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = aws_kms_key.platform.arn

  db_name                     = "mlflow"
  username                    = "mlflow"
  manage_master_user_password = true # RDS creates the password in Secrets Manager; it never appears in Terraform

  db_subnet_group_name   = aws_db_subnet_group.mlflow[0].name
  vpc_security_group_ids = [aws_security_group.mlflow_db[0].id]
  publicly_accessible    = false
  multi_az               = false # production: true (a standby in a second zone)

  backup_retention_period = 1
  # Lab settings, so destroy is quick and complete. Production: deletion_protection = true and a final snapshot.
  deletion_protection = false
  skip_final_snapshot = true
  apply_immediately   = true
}
