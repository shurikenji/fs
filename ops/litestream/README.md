# Litestream reference configuration

`key-vault.yml.example` replicates the isolated encrypted key inventory on the
ARM 4/24 VPS. Configure Oracle Object Storage credentials in the systemd
environment, not in Git. Restore the database with Litestream first, then
provide `KEY_VAULT_MASTER_KEY` from the separate password-manager/offline
recovery record; the database cannot decrypt inventory without it.
