"""
Script to set allowances for Polymarket trading.
This approves USDC and CTF tokens for the Polymarket exchange contracts.
"""
import os
from dotenv import load_dotenv

from web3 import Web3
from web3.constants import MAX_INT
from web3.middleware import ExtraDataToPOAMiddleware


def set_allowances():
    """Set allowances for USDC and CTF tokens to Polymarket contracts."""
    # Load .env from current directory or parent
    from pathlib import Path
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

    # Try multiple RPC endpoints for reliability
    rpc_urls = [
        'https://polygon-rpc.com',  # Public Polygon RPC
        'https://rpc.ankr.com/polygon',  # Ankr RPC
        'https://polygon.llamarpc.com',  # LlamaNodes
    ]
    
    rpc_url = None
    web3 = None
    
    # Try to connect to available RPC
    for url in rpc_urls:
        try:
            print(f'Attempting to connect to {url}...')
            test_web3 = Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': 10}))
            if test_web3.is_connected():
                rpc_url = url
                web3 = test_web3
                print(f'✓ Connected to {url}\n')
                break
        except Exception as e:
            print(f'✗ Failed: {e}')
            continue
    
    if not web3:
        raise Exception('Could not connect to any Polygon RPC endpoint. Please check your internet connection.')
    priv_key = os.getenv('PK')  # Polygon account private key (needs some MATIC)
    pub_key = os.getenv('PBK')  # Polygon account public key corresponding to private key

    if not priv_key:
        raise ValueError("PK (private key) not found in .env file")
    if not pub_key:
        raise ValueError("PBK (public key/address) not found in .env file")

    chain_id = 137

    erc20_approve = '''[{"constant": false,"inputs": [{"name": "_spender","type": "address" },{ "name": "_value", "type": "uint256" }],"name": "approve","outputs": [{ "name": "", "type": "bool" }],"payable": false,"stateMutability": "nonpayable","type": "function"}]'''
    erc1155_set_approval = '''[{"inputs": [{ "internalType": "address", "name": "operator", "type": "address" },{ "internalType": "bool", "name": "approved", "type": "bool" }],"name": "setApprovalForAll","outputs": [],"stateMutability": "nonpayable","type": "function"}]'''

    usdc_address = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'
    ctf_address = '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045'

    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    balance = web3.eth.get_balance(pub_key)

    if balance == 0:
        raise Exception('No MATIC in your wallet. Please add some MATIC for gas fees.')
    
    print(f'Current MATIC balance: {web3.from_wei(balance, "ether")} MATIC')

    nonce = web3.eth.get_transaction_count(pub_key)

    usdc = web3.eth.contract(address=usdc_address, abi=erc20_approve)
    ctf = web3.eth.contract(address=ctf_address, abi=erc1155_set_approval)

    print('\nSetting allowances for Polymarket contracts...\n')

    # CTF Exchange
    print('1. Approving USDC for CTF Exchange...')
    raw_usdc_approve_txn = usdc.functions.approve('0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E', int(MAX_INT, 0)
    ).build_transaction({'chainId': chain_id, 'from': pub_key, 'nonce': nonce, 'gasPrice': web3.eth.gas_price})
    signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
    send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
    usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
    print(f'   ✓ Transaction: {usdc_approve_tx_receipt.transactionHash.hex()}')

    # Wait a moment and get updated nonce
    import time
    time.sleep(2)
    nonce = web3.eth.get_transaction_count(pub_key)

    print('2. Approving CTF tokens for CTF Exchange...')
    raw_ctf_approval_txn = ctf.functions.setApprovalForAll('0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E', True).build_transaction({'chainId': chain_id, 'from': pub_key, 'nonce': nonce, 'gasPrice': web3.eth.gas_price})
    signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
    send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
    ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
    print(f'   ✓ Transaction: {ctf_approval_tx_receipt.transactionHash.hex()}')

    time.sleep(2)
    nonce = web3.eth.get_transaction_count(pub_key)

    # Neg Risk CTF Exchange
    print('3. Approving USDC for Neg Risk CTF Exchange...')
    raw_usdc_approve_txn = usdc.functions.approve('0xC5d563A36AE78145C45a50134d48A1215220f80a', int(MAX_INT, 0)
    ).build_transaction({'chainId': chain_id, 'from': pub_key, 'nonce': nonce, 'gasPrice': web3.eth.gas_price})
    signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
    send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
    usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
    print(f'   ✓ Transaction: {usdc_approve_tx_receipt.transactionHash.hex()}')

    time.sleep(2)
    nonce = web3.eth.get_transaction_count(pub_key)

    print('4. Approving CTF tokens for Neg Risk CTF Exchange...')
    raw_ctf_approval_txn = ctf.functions.setApprovalForAll('0xC5d563A36AE78145C45a50134d48A1215220f80a', True).build_transaction({'chainId': chain_id, 'from': pub_key, 'nonce': nonce, 'gasPrice': web3.eth.gas_price})
    signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
    send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
    ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
    print(f'   ✓ Transaction: {ctf_approval_tx_receipt.transactionHash.hex()}')

    time.sleep(2)
    nonce = web3.eth.get_transaction_count(pub_key)

    # Neg Risk Adapter
    print('5. Approving USDC for Neg Risk Adapter...')
    raw_usdc_approve_txn = usdc.functions.approve('0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296', int(MAX_INT, 0)
    ).build_transaction({'chainId': chain_id, 'from': pub_key, 'nonce': nonce, 'gasPrice': web3.eth.gas_price})
    signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
    send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
    usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
    print(f'   ✓ Transaction: {usdc_approve_tx_receipt.transactionHash.hex()}')

    time.sleep(2)
    nonce = web3.eth.get_transaction_count(pub_key)

    print('6. Approving CTF tokens for Neg Risk Adapter...')
    raw_ctf_approval_txn = ctf.functions.setApprovalForAll('0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296', True).build_transaction({'chainId': chain_id, 'from': pub_key, 'nonce': nonce, 'gasPrice': web3.eth.gas_price})
    signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
    send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
    ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
    print(f'   ✓ Transaction: {ctf_approval_tx_receipt.transactionHash.hex()}')

    print('\n✅ All allowances set successfully!')
    print('Your wallet is now ready to place orders on Polymarket.')


if __name__ == '__main__':
    try:
        set_allowances()
    except Exception as e:
        print(f'\n❌ Error: {e}')
        import traceback
        traceback.print_exc()
        exit(1)

