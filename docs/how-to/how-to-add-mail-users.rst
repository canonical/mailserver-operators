.. meta::
   :description: Learn how to add Dovecot mail users through a Juju secret, grant application access, and update credentials.

.. _how_to_add_mail_users:

How to add mail users
=====================

Use the ``mail-users`` configuration option to provide Dovecot with mailbox
usernames and password hashes through a Juju secret. This secret is the only
way to add mail users to the charm. You need a deployed Dovecot application and
model administrator permissions to manage Juju secrets. The examples use the
application name ``dovecot``; replace it with your application name and select its
Juju model before running the commands.

Prepare mail-user credentials
-----------------------------

Each credential must have the format ``username:password-hash``. Crypt hashes
encode the password's hash, salt, and algorithm identifier in a single string.
Only ``$1$`` (MD5-crypt), ``$5$`` (SHA-256-crypt), ``$6$`` (SHA-512-crypt), and ``$y$``
(yescrypt) formats are supported. If you obtain users from LDAP or a database,
ensure that the exported password hashes use one of these formats.

Email-style usernames are normalized to their bare account names. For example,
``alice@example.com`` becomes ``alice``. Each normalized username must be unique, so
``alice@example.com`` and ``alice@example.org`` cannot be separate users.

Create a Juju secret
--------------------

Create a secret with a ``users`` field containing a YAML list of credentials:

.. code-block:: shell

   juju add-secret dovecot-mail-users \
       users='["alice:<alice-password-hash>", "bob:<bob-password-hash>"]'

Replace the placeholders with complete supported crypt hashes, and adjust the
list for your users. Keep the single quotes around the list to prevent the
shell from expanding the ``$`` characters in the hashes.

For a manually added user, this alternative prompts for Alice's password and
creates the secret using its SHA-512 crypt hash:

.. code-block:: shell

   juju add-secret dovecot-mail-users users="[\"alice:$(openssl passwd -6)\"]"

The plain text password is not recorded in shell history or passed as a command
argument.

Whichever method you use, ``juju add-secret`` prints the secret's URI, such as
``secret:<id>``. Save this URI for the configuration step.

Grant access and configure Dovecot
---------------------------------

Grant the application access to the secret:

.. code-block:: shell

   juju grant-secret dovecot-mail-users dovecot

Set ``mail-users`` to the URI printed by ``juju add-secret``:

.. code-block:: shell

   juju config dovecot mail-users=secret:<id>

Replace ``secret:<id>`` with the actual URI. Creating or granting the secret alone
does not configure the charm; the ``mail-users`` option must reference it.

Verify the configuration
------------------------

Check the application's status:

.. code-block:: shell

   juju status dovecot

Once the deployment's other requirements are satisfied, its units should be
active. A missing or inaccessible secret, a missing ``users`` field, or invalid
credentials causes the charm to report a blocked status. An empty user list
also leaves the application blocked.

Add users or change passwords
-----------------------------

Update the existing secret with the complete user list, including any new users
or replacement password hashes:

.. code-block:: shell

   juju update-secret dovecot-mail-users \
       users='["alice:<alice-password-hash>", "bob:<bob-password-hash>", "carol:<carol-password-hash>"]'

Replace the placeholders with complete supported crypt hashes.

.. important::

   Updating the ``users`` field replaces the entire list; it does not append entries.
   Retain every user who should continue to authenticate. Omitting a user removes
   their credentials from Dovecot authentication.

The charm applies secret revisions automatically. Check the application status
after each update.

Protect mail-user secrets
-------------------------

Mail users and their credentials are not backed up or restored by Bacula.
Use Vault or another appropriate secrets-management method to manage and
separately protect the secret. See Juju's `How to manage secrets
<https://canonical.com/juju/docs/juju-cli/3.6/howto/manage-secrets/>`_
and :ref:`How to back up and restore <how_to_back_up_restore>` for more details.
