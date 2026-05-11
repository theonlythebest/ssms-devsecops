data "aws_ami" "ubuntu" {
  most_recent = true

  owners = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "ssms_sg" {

  name = "ssms-security-group"

  ingress {
    description = "SSH"

    from_port = 22
    to_port   = 22

    protocol = "tcp"

    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Frontend"

    from_port = 80
    to_port   = 80

    protocol = "tcp"

    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Grafana"

    from_port = 3000
    to_port   = 3000

    protocol = "tcp"

    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Prometheus"

    from_port = 9090
    to_port   = 9090

    protocol = "tcp"

    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {

    from_port = 0
    to_port   = 0

    protocol = "-1"

    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "ssms_vm" {

  ami = data.aws_ami.ubuntu.id

  instance_type = "t2.micro"

  key_name = "ssms-key"

  vpc_security_group_ids = [
    aws_security_group.ssms_sg.id
  ]

  user_data = <<-EOF
              #!/bin/bash
              apt update -y
              apt install docker.io docker-compose -y
              systemctl start docker
              systemctl enable docker
              EOF

  tags = {
    Name = "SSMS-DevSecOps"
  }
}