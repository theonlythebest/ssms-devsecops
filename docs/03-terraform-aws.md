# 3. AWS + Terraform deep-dive

## 3.1 What is "Infrastructure as Code"?

For decades, building a server meant logging into a web console, clicking
through wizards, taking notes in a wiki, and hoping you could rebuild it
later. That world has well-known problems:

- **Snowflake servers**: two boxes that started identical drift apart over
  time and you can't reliably tell why.
- **No history**: who opened port 3389? When? Nobody remembers.
- **No review**: clicking through a console is invisible to peers.
- **Slow recovery**: if the box dies, rebuilding it is a manual ordeal.

**Infrastructure as Code (IaC)** is the practice of expressing the desired
state of infrastructure as text files in a Git repo, then having a tool make
reality match that text.

Benefits:

- **Reproducible**: `terraform apply` from the same files always yields the
  same infrastructure.
- **Reviewable**: changes go through pull requests, with a diff, with comments.
- **Auditable**: `git log` is the history. Who, when, why.
- **Disposable**: throw away your EC2, run `apply` again, you have an identical one.
- **Composable**: same code can deploy dev/stage/prod with one variable change.

Terraform is the most popular IaC tool. It's declarative (you describe the
*what*, Terraform figures out the *how*), cloud-agnostic (one syntax for AWS,
Azure, GCP), and free.

## 3.2 What Terraform does in this project

Terraform's responsibility ends where the operating system begins. Concretely,
it produces the empty EC2 + firewall, then hands off to Ansible.

```
terraform apply
  │
  ├─ Looks up the latest Ubuntu 24.04 AMI in eu-west-3
  ├─ Creates a security group with the right ingress rules
  ├─ Launches a t2.micro EC2 attached to that SG, with our key pair
  ├─ Cloud-init: installs docker.io (rough fallback if Ansible can't run)
  └─ Outputs the public IP
```

After that, Ansible (section 4) does the real configuration.

## 3.3 The files

The Terraform configuration lives in `terraform/` and is small on purpose.

```
terraform/
├── provider.tf         # which cloud, which region, which provider version
├── main.tf             # AMI lookup + security group + EC2 instance
├── outputs.tf          # public_ip output
├── terraform.tfstate         # generated, holds the real state
└── terraform.tfstate.backup  # automatic safety copy
```

### 3.3.1 `provider.tf` — line by line

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-3"
}
```

- The `terraform` block pins the AWS provider to the v5.x major. The `~>`
  operator allows minor/patch updates but blocks a breaking v6.x bump.
- The `provider "aws"` block sets the region. `eu-west-3` = Paris. All
  resources without an explicit region inherit this default.
- AWS **credentials** are not in the file (they shouldn't be). Terraform
  reads them from environment (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
  or from `~/.aws/credentials`. This is a deliberate security choice.

### 3.3.2 `main.tf` — line by line

**AMI lookup**

```hcl
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]      # Canonical's AWS account
  filter { name = "name"; values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"] }
  filter { name = "architecture"; values = ["x86_64"] }
  filter { name = "virtualization-type"; values = ["hvm"] }
}
```

- A `data` block reads existing AWS state (it does **not** create anything).
- We ask AWS: "of all AMIs owned by Canonical, find the most recent that
  matches Ubuntu 24.04 amd64 on gp3 SSD". This way we never have to hard-code
  an AMI ID — it would go stale within months.

**Security group (the AWS-side firewall)**

```hcl
resource "aws_security_group" "ssms_sg" {
  name = "ssms-security-group"

  ingress { from_port = 22;   to_port = 22;   protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }  # SSH
  ingress { from_port = 80;   to_port = 80;   protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }  # Frontend
  ingress { from_port = 3000; to_port = 3000; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }  # Grafana
  ingress { from_port = 9090; to_port = 9090; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }  # Prometheus

  egress  { from_port = 0;    to_port = 0;    protocol = "-1"; cidr_blocks = ["0.0.0.0/0"] }  # all
}
```

- A security group is **stateful**: if traffic is allowed in, return traffic
  is automatically allowed out (so you don't have to symmetrically open egress).
- `cidr_blocks = ["0.0.0.0/0"]` means "the entire internet". In production you'd
  scope SSH to your office IP, Grafana to your VPN, etc.
- Note the missing port 8000 — the FastAPI backend is **intentionally** not
  reachable directly from the internet via this SG. (In practice we opened
  it on the test VM to demo `/docs` and `/metrics`; for a hardened deployment
  it would only be reachable through the frontend or a reverse-proxy.)
- Egress is wide open because the backend genuinely needs to talk to
  package mirrors, Docker Hub, GitHub during deployment.

**EC2 instance**

```hcl
resource "aws_instance" "ssms_vm" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t2.micro"
  key_name      = "ssms-key"

  vpc_security_group_ids = [aws_security_group.ssms_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              apt update -y
              apt install docker.io docker-compose -y
              systemctl start docker
              systemctl enable docker
              EOF

  tags = { Name = "SSMS-DevSecOps" }
}
```

- `instance_type = "t2.micro"` → free tier eligible (1 vCPU, 1 GB RAM).
- `key_name = "ssms-key"` → AWS will inject the **public** half of that key
  pair into the new EC2's `/home/ubuntu/.ssh/authorized_keys`. The private
  half stays on your laptop (or in `EC2_SSH_KEY` secret in CI).
- `user_data` is a tiny **cloud-init** script that runs the first boot only.
  It's a fallback so the box has Docker even if Ansible is never run. Ansible
  later upgrades Docker to the upstream Docker CE.
- `tags` show up in the AWS console and let us spot the right box.

### 3.3.3 `outputs.tf`

```hcl
output "public_ip" {
  value = aws_instance.ssms_vm.public_ip
}
```

After `terraform apply`, run `terraform output -raw public_ip` to get the
EC2's public IP. This is exactly the value that needs to land in the
Ansible inventory and in the `EC2_HOST` GitHub Secret.

### 3.3.4 `terraform.tfstate`

Terraform records what it built in a state file. **This file is sensitive**
(it stores resource IDs, sometimes secrets) and is in `.gitignore`. In
production you'd store it in an encrypted S3 bucket with DynamoDB locking;
for this demo it's local.

## 3.4 Why ports are what they are

| Port | Why open?                                           | Should it be open in production?                |
|------|-----------------------------------------------------|-------------------------------------------------|
| 22   | SSH so Ansible can configure the box                | Yes, but scope to a bastion or to your VPN IP    |
| 80   | The frontend (anonymous shop UI)                    | Yes, behind a TLS reverse-proxy                  |
| 3000 | Grafana dashboards                                  | No — should be behind an OAuth proxy / VPN       |
| 9090 | Prometheus UI                                       | No — same reasoning, internal tool only          |

Sections 10 and 14 go deeper into how this would be tightened.

## 3.5 What happens after `terraform apply`

```
$ terraform apply
... (asks for confirmation)
Apply complete! Resources: 2 added, 0 changed, 0 destroyed.

Outputs:
public_ip = "13.39.86.185"
```

At this point:
- The EC2 is **running** (it stays running, billed at ~$0/h on free tier or
  ~$0.012/h otherwise).
- It has Ubuntu 24.04 + docker.io running (from cloud-init).
- It is unconfigured beyond that — no app, no compose, no firewall.
- The next step is to run Ansible against `13.39.86.185`. See section 4.

## 3.6 How the infrastructure is recreated automatically

The whole point of IaC is that the EC2 is disposable.

```bash
# Scenario: someone destroyed the box
$ terraform destroy        # confirms, tears down
$ terraform apply          # new EC2, new IP, same shape
$ # then update inventory + re-run Ansible OR
$ # update EC2_HOST secret + click "Run workflow" on deploy.yml
```

The EC2 itself becomes a **cattle, not a pet** — interchangeable, no manual
state, every byte of configuration captured in the repo. This is one of the
core DevOps maturity signals.

## 3.7 Common questions

**"Why not run the app on Lambda / ECS / EKS?"**
Cost and simplicity. A t2.micro + Docker compose is enough for a demo and
keeps the architecture explicit. Moving to ECS would hide the moving parts
behind AWS-managed orchestration, which would obscure the educational value.

**"Why not Terraform Cloud / Spacelift?"**
Out of scope for the demo. Adding remote state would change one block in
`provider.tf` (`backend "s3" { ... }`).

**"Why is the SSH port open to 0.0.0.0/0?"**
For ease of grading: the evaluator needs to SSH from anywhere. The right
production answer is "scope to a bastion's IP", which is a one-line change.
