# ssh-learn zsh integration. Sourced from ~/.zshrc by the installer.

# Locate the ssh-learn program installed by pip/pipx (on PATH), with a
# fall back to the conventional user bin directory.
typeset -g SSH_LEARN_PROGRAM="${SSH_LEARN_PROGRAM:-$(command -v ssh-learn 2>/dev/null)}"
[[ -z "$SSH_LEARN_PROGRAM" && -x "$HOME/.local/bin/ssh-learn" ]] && \
    SSH_LEARN_PROGRAM="$HOME/.local/bin/ssh-learn"

# Prints "INDEX<TAB>DESTINATION" for the first non-option argument, so the
# caller can both identify the destination and slice the args before it.
_ssh_learn_find_destination() {
    local -a args
    args=("$@")

    local index=1
    local argument

    local -a options_with_values
    options_with_values=(
        -B -b -c -D -E -e -F -I -i -J -L -l -m
        -O -o -P -p -Q -R -S -W -w
    )

    while (( index <= ${#args[@]} )); do
        argument="${args[$index]}"

        if [[ "$argument" == "--" ]]; then
            (( index++ ))
            print -r -- "${index}"$'\t'"${args[$index]:-}"
            return
        fi

        if [[ "$argument" != -* ]]; then
            print -r -- "${index}"$'\t'"${argument}"
            return
        fi

        if (( ${options_with_values[(Ie)$argument]} )); then
            (( index += 2 ))
        else
            (( index++ ))
        fi
    done

    print -r -- "0"$'\t'""
}

_ssh_learn_should_record() {
    local argument

    for argument in "$@"; do
        case "$argument" in
            -G|-Q|-V|-O)
                return 1
                ;;
        esac
    done

    return 0
}

ssh() {
    local -a original_args
    original_args=("$@")

    local parsed destination
    local -i destination_index
    parsed="$(_ssh_learn_find_destination "${original_args[@]}")"
    destination_index="${parsed%%$'\t'*}"
    destination="${parsed#*$'\t'}"

    command ssh "${original_args[@]}"
    local ssh_status=$?

    if (( ssh_status == 0 )) &&
       (( destination_index > 0 )) &&
       [[ -n "$destination" ]] &&
       [[ -x "$SSH_LEARN_PROGRAM" ]] &&
       _ssh_learn_should_record "${original_args[@]}"; then

        # Everything before the destination influences the connection
        # (options); everything after it is the remote command, so skip it.
        local -a record_command
        record_command=("$SSH_LEARN_PROGRAM" record "$destination")

        local argument
        for argument in "${original_args[@]:0:$((destination_index - 1))}"; do
            record_command+=("--ssh-arg=${argument}")
        done

        local record_result
        record_result="$("${record_command[@]}" 2>/dev/null)"

        if [[ -n "$record_result" ]]; then
            local record_status="${record_result%%$'\t'*}"
            local learned_alias="${record_result#*$'\t'}"

            case "$record_status" in
                saved)
                    print
                    print -P "%F{green}Saved SSH connection:%f ssh $learned_alias"
                    ;;
                updated)
                    print
                    print -P "%F{yellow}Updated SSH connection:%f ssh $learned_alias"
                    ;;
            esac
        fi
    fi

    return "$ssh_status"
}

_ssh_learn_pick() {
    local prompt="$1"
    shift

    if ! command -v fzf >/dev/null 2>&1; then
        print -u2 "fzf is required. Install it with: brew install fzf"
        return 1
    fi

    local selected
    selected="$(
        "$SSH_LEARN_PROGRAM" list --sort used --names "$@" |
            fzf \
                --prompt="$prompt" \
                --height=70% \
                --reverse \
                --border \
                --preview="$SSH_LEARN_PROGRAM show {}" \
                --preview-window='right:55%'
    )"

    [[ -n "$selected" ]] && ssh "$selected"
}

# Fuzzy-pick a learned host and connect.
sshm() {
    _ssh_learn_pick "SSH host: "
}

# Fuzzy-pick among hosts carrying a tag and connect.
ssh-tag-connect() {
    local tag="${1:-}"

    if [[ -z "$tag" ]]; then
        print -u2 "Usage: ssh-tag-connect <tag>"
        return 1
    fi

    _ssh_learn_pick "SSH [$tag]: " --tag "$tag"
}

ssh-recent() {
    "$SSH_LEARN_PROGRAM" list --sort used
}

ssh-frequent() {
    "$SSH_LEARN_PROGRAM" list --sort count
}

ssh-tags() {
    local tag="${1:-}"

    if [[ -z "$tag" ]]; then
        print -u2 "Usage: ssh-tags <tag>"
        return 1
    fi

    "$SSH_LEARN_PROGRAM" list --tag "$tag" --sort used
}

ssh-learn() {
    "$SSH_LEARN_PROGRAM" "$@"
}

# ---------------------------------------------------------------------------
# Tab completion
# ---------------------------------------------------------------------------
# Learned aliases also complete for plain `ssh`, `scp`, and `sftp`: zsh's
# built-in ssh completion reads ~/.ssh/config and follows its Include lines.

_ssh_learn_complete_hosts() {
    local -a hosts
    hosts=(${(f)"$("$SSH_LEARN_PROGRAM" list --names 2>/dev/null)"})
    (( ${#hosts[@]} )) && compadd -- "${hosts[@]}"
}

_ssh_learn_complete_tags() {
    local -a tags
    tags=(${(f)"$("$SSH_LEARN_PROGRAM" tags --names 2>/dev/null)"})
    (( ${#tags[@]} )) && compadd -- "${tags[@]}"
}

_ssh_learn_complete() {
    local -a subcommands
    subcommands=(
        record list show remove rename relabel tag tags prune rebuild validate
    )

    if (( CURRENT == 2 )); then
        compadd -- "${subcommands[@]}"
        return
    fi

    local previous="${words[$((CURRENT - 1))]}"

    case "${words[2]}" in
        list)
            case "$previous" in
                --tag)  _ssh_learn_complete_tags; return ;;
                --sort) compadd -- name used count; return ;;
            esac
            compadd -- --tag --sort --names
            _ssh_learn_complete_hosts
            ;;
        show)
            _ssh_learn_complete_hosts
            ;;
        remove)
            compadd -- --dry-run
            _ssh_learn_complete_hosts
            ;;
        rename)
            # Only the first argument is an existing host;
            # the second is the new alias.
            (( CURRENT == 3 )) && _ssh_learn_complete_hosts
            ;;
        relabel)
            compadd -- --dry-run --force
            _ssh_learn_complete_hosts
            ;;
        tag)
            case "$previous" in
                --add)    return ;;  # new tag names are free-form
                --remove) _ssh_learn_complete_tags; return ;;
            esac
            compadd -- --add --remove
            _ssh_learn_complete_hosts
            ;;
        tags)
            compadd -- --names
            ;;
        prune)
            compadd -- --days --dry-run
            ;;
    esac
}

_ssh_tags_helper_complete() {
    (( CURRENT == 2 )) && _ssh_learn_complete_tags
}

_ssh_learn_register_completions() {
    compdef _ssh_learn_complete ssh-learn
    compdef _ssh_tags_helper_complete ssh-tags ssh-tag-connect
}

if (( $+functions[compdef] )); then
    _ssh_learn_register_completions
elif autoload -Uz compinit && compinit -C 2>/dev/null; then
    _ssh_learn_register_completions
fi
