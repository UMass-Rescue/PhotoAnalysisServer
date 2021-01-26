.. Citadel Server documentation master file, created by
   sphinx-quickstart on Tue Jan 26 12:38:25 2021.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Citadel Server Documentation
==========================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:


Core Modules
==========================================

Main
---------------------------------------------------------
.. automodule:: main
   :members:

.. note:: The main.py file is only used for startup/shutdown and registering routers. No actual
   computation or logic takes place in this file.


Dependency Server File
---------------------------------------------------------
.. automodule:: dependency
   :members:


Database Server File
---------------------------------------------------------
.. automodule:: db_connection
   :members:

HTTP Routers
==========================================

Model Prediction Router
---------------------------------------------------------
.. automodule:: routers.model
   :members:

Dataset and Training Router
---------------------------------------------------------
.. automodule:: routers.training
   :members:

Authentication Router
---------------------------------------------------------
.. automodule:: routers.auth
   :members:

Docker Worker
==========================================

Docker Workers
---------------------------------------------------------
.. automodule:: worker
   :members:


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
