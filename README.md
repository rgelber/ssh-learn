# ssh-learn

Automatically turn every successful SSH connection into a permanent, tidy alias.

Connect to a machine once — `ssh deploy@x.x.x.x` — and ssh-learn records it,
derives a sensible alias, and writes it into an SSH config that's included from
your `~/.ssh/config`. Next time, `ssh <alias>` just works, with tab completion and
an optional fuzzy picker.

## How it works

A tiny zsh wrapper around `ssh` notices when a connection succeeds and calls
`ssh-learn record` in the background. That command asks OpenSSH itself
(`ssh -G`) for the effective hostname, user, port, identity file, and proxy
jump, then renders a validated `~/.ssh/conf.d/90-learned.conf`. Your own
`~/.ssh/config` is only ever appended to (once), and always takes precedence.

Nothing leaves your machine. Optional remote "facts" (e.g. a Puppet
environment) are read over the same SSH session to auto-tag hosts, and can be
disabled entirely.

## Install

```sh
cd ssh-learn
pipx install .              # or: pip install --user ssh-learn
ssh-learn init              # writes the zsh integration, wires up ssh config
source ~/.zshrc
```

For the interactive picker, also install [`fzf`](https://github.com/junegunn/fzf).

Check everything is wired up correctly at any time:

```sh
ssh-learn doctor
```

## Usage

```
sshm                              fuzzy-pick a host and connect (needs fzf)
ssh-recent                        hosts by last use
ssh-frequent                      hosts by connection count
ssh-tags <tag>                    hosts carrying a tag
ssh-tag-connect <tag>             fuzzy-pick within a tag

ssh-learn list ['web-*']          list learned hosts (optional glob filter)
ssh-learn show <host...>          show hosts as JSON
ssh-learn tags                    list all tags in use
ssh-learn rename <host> <alias>   rename an alias (and lock it)
ssh-learn relabel [host...]       reset aliases to the name you connect with
ssh-learn tag <host...> --add x   manage manual tags
ssh-learn remove <host...>        forget hosts (supports globs)
ssh-learn prune --days 90         forget hosts unused for N days
```

Most host-taking commands accept multiple names, unique prefixes, and quoted
glob patterns (`'web-*'`), which match on alias, hostname, and tag.

### Aliases follow the name you connect with

If you `ssh hostname` and your config points that at `x.x.x.x`, the learned
alias is `hostname` — the name you actually type — not the IP. If some hosts
were learned under an older version with IP-derived names, fix them in place:

```sh
ssh-learn relabel --dry-run   # preview
ssh-learn relabel             # apply (skips names you set by hand)
```

## Uninstall

```sh
ssh-learn uninstall           # remove the shell integration, keep learned data
ssh-learn uninstall --purge   # also delete learned hosts, metadata, backups
pipx uninstall ssh-learn      # remove the program itself
```

`uninstall` only reverses what `init` added; a `Host *` block of your own is
never touched.

## Configuration

| Variable | Effect |
| --- | --- |
| `SSH_LEARN_HOME` | Use a different home directory (mainly for testing). |
| `SSH_LEARN_NO_FACTS` | Skip remote fact collection entirely. |
| `SSH_LEARN_FACTS_TTL_DAYS` | How long cached facts stay fresh (default 7). |

## Development

```sh
git clone https://github.com/yourname/ssh-learn
cd ssh-learn
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

make test        # run the pytest suite
make lint        # ruff
make check       # both
```

The package is deliberately dependency-free at runtime and split into small,
single-responsibility modules (`naming`, `store`, `sshcfg`, `facts`,
`recorder`, `commands`, `installer`, `cli`). The zsh integration and default
SSH options live in `src/ssh_learn/data/`.

## License

MIT — see [LICENSE](LICENSE).
