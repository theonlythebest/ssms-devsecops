# 4. Ansible deep-dive

## 4.1 What is Ansible?

**Ansible is a configuration management tool.** It connects to remote machines
over SSH (no agent to install on the target) and runs a sequence of declarative
tasks — *install this package, copy that file, start this service, open this
firewall port* — until the remote box matches a desired state.

Key properties:

- **Agentless**: Ansible only needs SSH on the target and Python (which Ubuntu
  has by default). Nothing to maintain on the target.
- **Declarative + idempotent**: each task describes a goal ("port 8000 is open
  in UFW"). If the goal is already met, the task does nothing. You can run
  the same playbook ten times and the box ends up identical.
- **Human-readable YAML**: anyone who can read English can read a playbook.
- **Modular**: roles are reusable packages of tasks.

## 4.2 How Ansible fits in the stack

```
Terraform              Ansible              Docker
  │                       │                    │
  │  builds the EMPTY     │  configures the    │  runs the app
  │  EC2 (just an OS)     │  EC2 (Docker,      │  itself
  │                       │  firewall, git     │
  │                       │  clone, compose up)│
  ▼                       ▼                    ▼
"a server exists"   "the server is ready"  "the app is live"
```

Terraform answers **"what infrastructure exists?"**.
Ansible answers **"what is on that infrastructure?"**.
Docker answers **"what is running inside that?"**.

You could in theory do all three with Ansible alone (it has AWS modules), or
all three with Terraform alone (it can run remote-exec). Splitting the
responsibilities keeps each tool playing to its strengths and the codebase
much easier to read.

## 4.3 Project layout

```
ansible/
├── ansible.cfg           # SSH/pipelining defaults, sudo, no host-key prompts
├── inventory.ini         # which machines + how to reach them
├── playbook.yml          # the top-level orchestration
├── requirements.yml      # Galaxy collections to install (community.docker, etc.)
├── group_vars/all.yml    # repo URL, ports, env vars - one source of truth
└── roles/
    ├── common/           # OS prep, base packages, UFW
    ├── docker/           # Docker engine + Compose plugin
    └── ssms/             # git clone + .env render + compose up + smoke tests
```

## 4.4 `ansible.cfg` — connection defaults

```ini
[defaults]
inventory            = ./inventory.ini
roles_path           = ./roles
host_key_checking    = False         # don't fail on first SSH connect
stdout_callback      = yaml          # human-friendly output
forks                = 10            # how many hosts in parallel
gathering            = smart         # cache facts between plays

[ssh_connection]
pipelining           = True          # 2-3x speedup
ssh_args             = -o ControlMaster=auto -o ControlPersist=300s ...

[privilege_escalation]
become              = True
become_method       = sudo
```

- `host_key_checking = False` is set because the EC2 is brand-new every time
  we destroy/apply; its host key will always be unknown the first time.
- `pipelining = True` collapses three SSH round-trips into one for most
  modules. Big speed-up on long playbooks.
- `become = True` means "run every task as root via sudo" by default. The
  `ubuntu` user has passwordless sudo in Ubuntu AMIs.

## 4.5 `inventory.ini` — who are we talking to?

```ini
[ssms]
ssms-prod ansible_host=13.39.86.185

[ssms:vars]
ansible_user                 = ubuntu
ansible_ssh_private_key_file = ~/.ssh/ssms-key.pem
ansible_python_interpreter   = /usr/bin/python3
```

- `[ssms]` is a **group** with one host called `ssms-prod`.
- `ansible_host` is the actual IP/DNS. We use a friendly name (`ssms-prod`)
  so the playbook can keep referring to the same handle even if the IP
  changes.
- The `:vars` section sets connection defaults for the whole group.
- In CI (`deploy.yml`) this file is **regenerated from secrets** so the IP
  and SSH key never end up in source control.

## 4.6 `playbook.yml` — the orchestrator

```yaml
- name: Deploy SSMS DevSecOps stack
  hosts: ssms
  become: true
  gather_facts: true

  pre_tasks:
    - name: Wait for SSH / cloud-init to finish
      ansible.builtin.wait_for_connection:
        timeout: 300
        delay: 5
    - name: Wait for apt / cloud-init lock to release
      shell: |
        while fuser /var/lib/dpkg/lock-frontend ... ; do sleep 3; done

  roles:
    - role: common
    - role: docker
    - role: ssms

  post_tasks:
    - name: Print access URLs
      debug: { msg: [...] }
```

The order matters:

1. `wait_for_connection` — Ansible polls SSH until the box answers (the EC2
   might still be booting after Terraform).
2. The dpkg-lock-wait — cloud-init runs `apt install docker.io` in the
   background. If Ansible tries `apt install` at the same time, it'll fail
   on the lock. We wait until it's free.
3. **role: common** — base OS prep (timezone, base packages, UFW).
4. **role: docker** — official Docker repo, then `docker-ce` + Compose plugin.
5. **role: ssms** — clone the repo, render `.env`, run `docker compose up -d`,
   smoke-test the URLs.
6. `post_tasks` prints a summary so the operator gets the URL cheat sheet.

## 4.7 The three roles in detail

Roles are Ansible's reusable unit. Each role has a standard layout:

```
roles/<name>/
├── tasks/main.yml      # the work
├── defaults/main.yml   # variables with default values
├── handlers/main.yml   # triggered by `notify`, run at end of play
└── templates/          # Jinja2 templates
```

### 4.7.1 `roles/common`

Job: get the OS to a known-good baseline.

```yaml
- name: Set timezone
  community.general.timezone: { name: "{{ common_timezone }}" }

- name: Refresh apt cache (cached for 1h)
  ansible.builtin.apt:
    update_cache: true
    cache_valid_time: 3600

- name: Install base packages
  ansible.builtin.apt:
    name: ["ca-certificates", "curl", "git", "gnupg", "ufw", ...]
    state: present

- name: Ensure UFW default policies (deny incoming, allow outgoing)
  community.general.ufw:
    direction: "{{ item.direction }}"
    policy: "{{ item.policy }}"
  loop:
    - { direction: incoming, policy: deny  }
    - { direction: outgoing, policy: allow }

- name: Open required ports in UFW
  community.general.ufw:
    rule: allow
    port: "{{ item.port }}"
    proto: "{{ item.proto }}"
  loop: "{{ ssms_open_ports }}"      # 22, 80, 8000, 9090, 3000

- name: Enable UFW
  community.general.ufw:
    state: enabled
    logging: low
```

UFW is the **second** layer of firewall (the AWS security group is the
first). Defense in depth.

### 4.7.2 `roles/docker`

Job: install Docker Engine + Compose v2 plugin from Docker's upstream apt repo
(the Ubuntu-bundled `docker.io` is older and ships without the Compose plugin).

Highlights:

```yaml
- name: Ensure /etc/apt/keyrings exists
  file: { path: /etc/apt/keyrings, state: directory, mode: "0755" }

- name: Add Docker GPG key (dearmored)
  shell: |
    set -euo pipefail
    curl -fsSL {{ docker_apt_repo_url }}/gpg | gpg --dearmor -o {{ docker_apt_keyring }}
    chmod a+r {{ docker_apt_keyring }}
  args:
    creates: "{{ docker_apt_keyring }}"   # idempotency

- name: Add Docker apt repository
  copy:
    dest: "{{ docker_apt_repo_list }}"
    content: |
      deb [arch={{ docker_apt_arch }} signed-by={{ docker_apt_keyring }}] {{ docker_apt_repo_url }} {{ docker_apt_release }} stable

- name: Install Docker Engine + Compose plugin
  apt: { name: [docker-ce, docker-ce-cli, containerd.io, docker-buildx-plugin, docker-compose-plugin], state: present }

- name: Add users to the docker group (no sudo needed)
  user: { name: "{{ item }}", groups: docker, append: true }
  loop: "{{ docker_users }}"   # ubuntu

- name: Verify Docker is callable
  command: docker --version
  register: docker_version
  changed_when: false           # this is a check, not a mutation
```

Adding the user to the `docker` group means `docker` commands run without
`sudo` for that user later. The `changed_when: false` on verification tasks
keeps Ansible's "what changed" report honest.

### 4.7.3 `roles/ssms`

Job: deploy the actual application.

```yaml
- name: Ensure app directory exists
  file: { path: "{{ ssms_app_dir }}", state: directory, owner: ubuntu, group: ubuntu, mode: "0755" }

- name: Clone / update SSMS repository
  git:
    repo: "{{ ssms_git_repo }}"
    dest: "{{ ssms_app_dir }}"
    version: "{{ ssms_git_branch }}"
    force: true
    update: true
  become_user: "{{ ssms_app_user }}"

- name: Render backend .env from variables
  template:
    src: env.j2
    dest: "{{ ssms_app_dir }}/.env"
    mode: "0640"

- name: Bring SSMS stack up (idempotent)
  community.docker.docker_compose_v2:
    project_src: "{{ ssms_app_dir }}"
    state: present
    pull: always
    wait: true
    wait_timeout: 180

- name: Smoke test - backend /health
  uri:
    url: "{{ ssms_health_url }}"
    status_code: 200
  retries: 20
  delay: 5
  until: smoke_health.status == 200
```

The seam between **secrets** and **code** lives in the `template` task: the
Jinja2 template `env.j2` reads from `group_vars/all.yml`, and in CI those
variables come from GitHub Secrets via `-e ssms_env.JWT_SECRET=...`. The
.env file lands on disk with mode `0640` (owner read+write, group read,
world nothing).

## 4.8 Idempotency in practice

Every Ansible task is either:

- A **module call** that's idempotent by construction (`apt`, `file`, `user`,
  `ufw`, `git`, `docker_compose_v2`).
- A **shell/command call** that's guarded by `creates:` (skip if the output
  file already exists) or `changed_when: false` (just a query).

If you run `ansible-playbook playbook.yml` twice in a row, the second run
prints `ok=N changed=0` for every task — the system is already in the
desired state. This is the difference between *imperative scripts* (do these
commands) and *declarative playbooks* (the system shall be in this state).

## 4.9 Why use Ansible at all if we have Docker?

Docker can't:

- Install itself.
- Open a host firewall port.
- Pull a Git repo onto the host.
- Render a file based on host-side variables.
- Run smoke tests after the stack comes up.

Ansible can do all of that, and once it's done, Docker takes over for the
runtime. The split keeps responsibilities clean and the system explainable.

## 4.10 What can go wrong + how the playbook handles it

| Failure                          | Mitigation                                                                |
|----------------------------------|---------------------------------------------------------------------------|
| EC2 not booted yet               | `wait_for_connection` retries for 5 minutes                               |
| Cloud-init still apt-installing  | dpkg-lock waiter blocks until it's done                                   |
| Docker GPG key fetch flaky       | `creates:` idempotency means a second run re-tries                        |
| Backend takes a minute to start  | `wait: true, wait_timeout: 180` + smoke test retries 20× 5s               |
| docker compose `pull` fails      | `failed_when: false` on the pull task — compose-up will surface a real error if there is one |
| Image registries down            | playbook fails loud at compose-up; ops sees the error and reruns later    |
