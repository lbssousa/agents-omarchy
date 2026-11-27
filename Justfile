set shell := ["bash", "-uc"]

plugin_link := env("HOME") / ".config/omarchy/plugins/lbssousa.agents"

default:
    @just --list

# Plugin validation
validate:
    omarchy-plugin-validate .

# Load this checkout's plugin in the real shell
link:
    ln -sfn "$PWD" {{plugin_link}}
    omarchy-shell shell rescanPlugins
    omarchy-shell shell enablePlugin lbssousa.agents '{}'
    omarchy-restart-shell
