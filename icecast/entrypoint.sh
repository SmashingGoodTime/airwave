#!/bin/sh
# Render the Icecast config from the mounted template, injecting the source and
# admin passwords from the environment into a writable temp copy.
#
# Why not just mount icecast.xml at /etc/icecast.xml and let the image's own
# entrypoint patch it? The container runs as the non-root "icecast" user and
# the baked-in /etc/icecast.xml is not replaceable by it, and a :ro bind mount
# there cannot be patched in place. Rendering to /tmp sidesteps both problems.
set -eu

TEMPLATE="${ICECAST_TEMPLATE:-/etc/icecast.tmpl.xml}"
RENDERED="/tmp/icecast.xml"

# XML-escape (&, <, >) so the value is valid inside an element, then escape for
# a sed replacement (\, /, &) so it is inserted literally regardless of content.
prep() {
    printf '%s' "$1" \
        | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' \
        | sed -e 's/[\\/&]/\\&/g'
}

SRC=$(prep "${ICECAST_SOURCE_PASSWORD:-hackme}")
ADM=$(prep "${ICECAST_ADMIN_PASSWORD:-hackme}")

sed \
    -e "s/@ICECAST_SOURCE_PASSWORD@/${SRC}/g" \
    -e "s/@ICECAST_ADMIN_PASSWORD@/${ADM}/g" \
    "$TEMPLATE" > "$RENDERED"

exec icecast -c "$RENDERED"
