# Android signing key

`vidharbor-release.jks` signs the VidHarbor Android APKs, so every new version installs
over the previous one. It is committed here so GitHub can build releases with no setup.

Because this repository is public, anyone can read this key. To keep it private:

1. Base64-encode a keystore (this one, or a new one): `base64 -w0 vidharbor-release.jks`
2. In GitHub: Settings → Secrets and variables → Actions → New repository secret:
   - `ANDROID_KEYSTORE_B64` – the base64 text
   - `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`
3. Delete `vidharbor-release.jks` from the repository.

The workflow uses the secrets when they exist. Switching to a *different* key means
people must uninstall the old app once before installing the new one.
