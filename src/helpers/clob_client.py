import os
from dotenv import load_dotenv

try:
    from py_clob_client.client import ClobClient
except Exception:  # Backward compatibility for older versions
    from py_clob_client import ClobClient  # type: ignore


def create_clob_client() -> "ClobClient":
    """
    Build a ClobClient using env vars.
    Required: HOST (CLOB endpoint), PK (private key)
    Optional: CLOB_API_KEY, CLOB_SECRET, CLOB_PASS_PHRASE
    """
    load_dotenv()

    host = os.getenv("HOST", "https://clob.polymarket.com")
    pk_env = os.getenv("PK")
    pk = pk_env
    pbk = os.getenv("PBK")  # optional public address
    if not pk:
        raise RuntimeError("PK is required in environment to create ClobClient")
    # Prepare both formats: raw hex and 0x-prefixed
    pk = pk.strip()
    pk_raw = pk[2:] if pk.startswith("0x") else pk
    pk_0x = pk if pk.startswith("0x") else ("0x" + pk)

    # Expose to any downstream that reads env directly
    os.environ.setdefault("POLY_PRIVATE_KEY", pk_raw)
    os.environ.setdefault("PRIVATE_KEY", pk_raw)
    os.environ.setdefault("PK", pk_env)
    if pbk:
        os.environ.setdefault("POLY_ADDRESS", pbk)
        os.environ.setdefault("PUBLIC_ADDRESS", pbk)

    # Initialize per Polymarket docs: EOA trading uses key + chain_id
    try:
        client = ClobClient(host, key=pk_raw, chain_id=137)  # type: ignore[call-arg]
    except TypeError:
        # Older versions may not accept named params
        client = ClobClient(host)

    # Attach L1 signer/private key using whatever API the installed version supports
    # Attempt to attach L1 signer for legacy client APIs as a fallback
    try:
        if hasattr(client, "set_private_key"):
            client.set_private_key(pk_raw)  # type: ignore[attr-defined]
        elif hasattr(client, "set_l1_credentials"):
            try:
                client.set_l1_credentials(pk_raw, pbk)  # type: ignore[attr-defined]
            except TypeError:
                client.set_l1_credentials(pk_raw)  # type: ignore[attr-defined]
        elif hasattr(client, "set_wallet"):
            client.set_wallet(pk_raw, pbk) if pbk else client.set_wallet(pk_raw)  # type: ignore[attr-defined]
    except Exception:
        pass

    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASS_PHRASE")

    # Prefer provided API creds; otherwise derive from L1 private key if available in client
    # Always use the client's helper to obtain the correct creds object for this version
    try:
        if api_key and api_secret and api_passphrase:
            # Ensure env is set so the helper can pick them up if needed
            os.environ["CLOB_API_KEY"] = api_key
            os.environ["CLOB_SECRET"] = api_secret
            os.environ["CLOB_PASS_PHRASE"] = api_passphrase
        client.set_api_creds(client.create_or_derive_api_creds())  # type: ignore[call-arg]
    except Exception:
        pass

    return client


