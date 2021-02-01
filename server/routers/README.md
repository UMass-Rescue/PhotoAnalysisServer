# API Routers

This directory contains routers for the different areas of the server. A router handles
all the logic for an aspect of the server. This organizational structure is used to minimize
clutter and group associated actions.

Routers all share a base url, and have their endpoints based on that. For example, the
authentication router (`auth.py`) has all of its endpoints start with auth.
`/auth/login`
`/auth/profile`
etc...

Routers are registered with the server in `/server/main.py`