# SSMS - Ansible

End-to-end provisioning of the SSMS DevSecOps stack onto a fresh Ubuntu EC2
instance produced by Terraform.

## Layout

```
ansible/
├── ansible.cfg          # connection defaults, sudo, pipelining
├── inventory.ini        # target EC2 (ssms-prod @ 13.39.86.185)
├── playbook.yml         # top-level orchestration
├── requirements.yml     # required Galaxy collections
├── group_vars/all.yml   # repo URL, env vars, ports, smoke-test URLs
└── roles/
    ├── common/          # OS prep, ufw, base packages
    ├── docker/          # Docker Engine + Compose v2 plugin
    └── ssms/            # git clone + docker compose up + smoke tests
```

## Prerequisites (on your workstation)

```
pip install "ansible-core>=2.16"
ansible-galaxy collection install -r requirements.yml
chmod 600 ~/.ssh/ssms-key.pem
```

## Deploy

```
cd ansible
ansible-playbook -i inventory.ini playbook.yml
```

Re-runs are idempotent.

## Common overrides

```
# deploy a feature branch instead of main
ansible-playbook -i inventory.ini playbook.yml \
    -e ssms_git_branch=feature/new-thing

# force-recreate all containers
ansible-playbook -i inventory.ini playbook.yml \
    -e ssms_compose_recreate=true

# point at a different host on the fly
ansible-playbook -i inventory.ini playbook.yml \
    -e ansible_host=1.2.3.4
```

## Driving from Terraform output (optional)

If you'd rather not edit `inventory.ini` by hand every time Terraform
recreates the EC2, add an output for the public IP and regenerate the
inventory before each run, e.g.:

```
terraform -chdir=../terraform output -raw public_ip \
  | xargs -I {} sed -i "s/ansible_host=.*/ansible_host={}/" inventory.ini
```
