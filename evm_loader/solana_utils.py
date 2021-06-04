from solana.transaction import AccountMeta, TransactionInstruction, Transaction
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solana.account import Account
from solana.publickey import PublicKey
from solana.rpc.commitment import Confirmed
import time
import os
import subprocess
from typing import NamedTuple
import json
from eth_keys import keys as eth_keys
import base64
from base58 import b58encode
from solana._layouts.system_instructions import SYSTEM_INSTRUCTIONS_LAYOUT, InstructionType as SystemInstructionType
from construct import Bytes, Int8ul, Int64ul, Struct as cStruct
from hashlib import sha256
from sha3 import keccak_256
import rlp

CREATE_ACCOUNT_LAYOUT = cStruct(
    "lamports" / Int64ul,
    "space" / Int64ul,
    "ether" / Bytes(20),
    "nonce" / Int8ul
)

system = "11111111111111111111111111111111"

solana_url = os.environ.get("SOLANA_URL", "http://localhost:8899")
EVM_LOADER = os.environ.get("EVM_LOADER")

EVM_LOADER_SO = os.environ.get("EVM_LOADER_SO", 'target/bpfel-unknown-unknown/release/evm_loader.so')
client = Client(solana_url)
path_to_solana = 'solana'


def confirm_transaction(http_client, tx_sig, confirmations=1):
    """Confirm a transaction."""
    TIMEOUT = 30  # 30 seconds  pylint: disable=invalid-name
    elapsed_time = 0
    while elapsed_time < TIMEOUT:
        print('confirm_transaction for %s', tx_sig)
        resp = http_client.get_signature_statuses([tx_sig])
        print('confirm_transaction: %s', resp)
        if resp["result"]:
            status = resp['result']['value'][0]
            if status and (status['confirmationStatus'] == 'finalized' or status['confirmationStatus'] == 'confirmed'
                           and status['confirmations'] >= confirmations):
                return
        sleep_time = 1
        time.sleep(sleep_time)
        elapsed_time += sleep_time
    raise RuntimeError("could not confirm transaction: ", tx_sig)


def accountWithSeed(base, seed, program):
    print(type(base), type(seed), type(program))
    return PublicKey(sha256(bytes(base) + bytes(seed, 'utf8') + bytes(program)).digest())


def createAccountWithSeed(funding, base, seed, lamports, space, program):
    data = SYSTEM_INSTRUCTIONS_LAYOUT.build(
        dict(
            instruction_type=SystemInstructionType.CreateAccountWithSeed,
            args=dict(
                base=bytes(base),
                seed=dict(length=len(seed), chars=seed),
                lamports=lamports,
                space=space,
                program_id=bytes(program)
            )
        )
    )
    print("createAccountWithSeed", data.hex())
    created = accountWithSeed(base, seed,
                              program)  # PublicKey(sha256(bytes(base)+bytes(seed, 'utf8')+bytes(program)).digest())
    print("created", created)
    return TransactionInstruction(
        keys=[
            AccountMeta(pubkey=funding, is_signer=True, is_writable=True),
            AccountMeta(pubkey=created, is_signer=False, is_writable=True),
            AccountMeta(pubkey=base, is_signer=True, is_writable=False),
        ],
        program_id=system,
        data=data
    )


class solana_cli:
    def __init__(self, acc=None):
        self.acc = acc

    def call(self, arguments):
        cmd = ""
        if self.acc == None:
            cmd = '{} --url {} {}'.format(path_to_solana, solana_url, arguments)
        else:
            cmd = '{} --keypair {} --url {} {}'.format(path_to_solana, self.acc.get_path(), solana_url, arguments)
        try:
            return subprocess.check_output(cmd, shell=True, universal_newlines=True)
        except subprocess.CalledProcessError as err:
            import sys
            print("ERR: solana error {}".format(err))
            raise


class neon_cli:
    def call(self, arguments):
        cmd = 'neon-cli --url {} {}'.format(solana_url, arguments)
        try:
            return subprocess.check_output(cmd, shell=True, universal_newlines=True)
        except subprocess.CalledProcessError as err:
            import sys
            print("ERR: neon-cli error {}".format(err))
            raise


class RandomAccount:
    def __init__(self, path=None):
        if path == None:
            self.make_random_path()
            print("New keypair file: {}".format(self.path))
            self.generate_key()
        else:
            self.path = path
        self.retrieve_keys()
        print('New Public key:', self.acc.public_key())
        print('Private:', self.acc.secret_key())

    def make_random_path(self):
        import calendar;
        import time;
        ts = calendar.timegm(time.gmtime())
        self.path = str(ts) + '.json'
        time.sleep(1)

    def generate_key(self):
        cmd_generate = 'solana-keygen new --no-passphrase --outfile {}'.format(self.path)
        try:
            return subprocess.check_output(cmd_generate, shell=True, universal_newlines=True)
        except subprocess.CalledProcessError as err:
            import sys
            print("ERR: solana error {}".format(err))
            raise

    def retrieve_keys(self):
        with open(self.path) as f:
            d = json.load(f)
            self.acc = Account(d[0:32])

    def get_path(self):
        return self.path

    def get_acc(self):
        return self.acc


class WalletAccount(RandomAccount):
    def __init__(self, path):
        self.path = path
        self.retrieve_keys()
        print('Wallet public key:', self.acc.public_key())


class EvmLoader:
    def __init__(self, acc, programId=EVM_LOADER):
        if programId == None:
            print("Load EVM loader...")
            result = json.loads(solana_cli(acc).call('deploy {}'.format(EVM_LOADER_SO)))
            programId = result['programId']
        EvmLoader.loader_id = programId
        print("Done\n")

        self.loader_id = EvmLoader.loader_id
        self.acc = acc
        print("Evm loader program: {}".format(self.loader_id))

    def deploy(self, contract_path, caller=None):
        output = neon_cli().call("deploy --evm_loader {} {} {}".format(self.loader_id, contract_path, caller))
        print(type(output), output)
        result = json.loads(output.splitlines()[-1])
        return result

    def createEtherAccount(self, ether):
        if isinstance(ether, str):
            if ether.startswith('0x'): ether = ether[2:]
        else:
            ether = ether.hex()
        (sol, nonce) = self.ether2program(ether)
        print('createEtherAccount: {} {} => {}'.format(ether, nonce, sol))
        trx = Transaction()
        base = self.acc.get_acc().public_key()
        trx.add(TransactionInstruction(
            program_id=self.loader_id,
            data=bytes.fromhex('02000000') + CREATE_ACCOUNT_LAYOUT.build(dict(
                lamports=10 ** 9,
                space=0,
                ether=bytes.fromhex(ether),
                nonce=nonce)),
            keys=[
                AccountMeta(pubkey=base, is_signer=True, is_writable=False),
                AccountMeta(pubkey=PublicKey(sol), is_signer=False, is_writable=True),
                AccountMeta(pubkey=system, is_signer=False, is_writable=False),
            ]))
        result = send_transaction(client, trx, self.acc.get_acc())
        print('result:', result)
        return sol

    def ether2seed(self, ether):
        if isinstance(ether, str):
            if ether.startswith('0x'): ether = ether[2:]
        else:
            ether = ether.hex()
        seed = b58encode(bytes.fromhex(ether)).decode('utf8')
        acc = accountWithSeed(self.acc.get_acc().public_key(), seed, PublicKey(self.loader_id))
        print('ether2program: {} {} => {}'.format(ether, 255, acc))
        return (acc, 255)

    def ether2program(self, ether):
        if isinstance(ether, str):
            if ether.startswith('0x'): ether = ether[2:]
        else:
            ether = ether.hex()
        output = neon_cli().call("create-program-address --evm_loader {} {}".format(self.loader_id, ether))
        items = output.rstrip().split(' ')
        return (items[0], int(items[1]))

    def checkAccount(self, solana):
        info = client.get_account_info(solana)
        print("checkAccount({}): {}".format(solana, info))

    def deployChecked(self, location, caller, caller_ether):
        trx_count = getTransactionCount(client, caller)
        ether = keccak_256(rlp.encode((caller_ether, trx_count))).digest()[-20:]

        program = self.ether2program(ether)
        code = self.ether2seed(ether)
        info = client.get_account_info(program[0])
        if info['result']['value'] is None:
            res = self.deploy(location, caller)
            return (res['programId'], bytes.fromhex(res['ethereum'][2:]), res['codeId'])
        elif info['result']['value']['owner'] != self.loader_id:
            raise Exception("Invalid owner for account {}".format(program))
        else:
            return (program[0], ether, code[0])

    def createEtherAccountTrx(self, ether, code_acc=None):
        if isinstance(ether, str):
            if ether.startswith('0x'): ether = ether[2:]
        else:
            ether = ether.hex()
        (sol, nonce) = self.ether2program(ether)
        print('createEtherAccount: {} {} => {}'.format(ether, nonce, sol))
        seed = b58encode(bytes.fromhex(ether))
        base = self.acc.get_acc().public_key()
        data = bytes.fromhex('02000000') + CREATE_ACCOUNT_LAYOUT.build(dict(
            lamports=10 ** 9,
            space=0,
            ether=bytes.fromhex(ether),
            nonce=nonce))
        trx = Transaction()
        if code_acc is None:
            trx.add(TransactionInstruction(
                program_id=self.loader_id,
                data=data,
                keys=[
                    AccountMeta(pubkey=base, is_signer=True, is_writable=True),
                    AccountMeta(pubkey=PublicKey(sol), is_signer=False, is_writable=True),
                    AccountMeta(pubkey=system, is_signer=False, is_writable=False),
                ]))
        else:
            trx.add(TransactionInstruction(
                program_id=self.loader_id,
                data=data,
                keys=[
                    AccountMeta(pubkey=base, is_signer=True, is_writable=True),
                    AccountMeta(pubkey=PublicKey(sol), is_signer=False, is_writable=True),
                    AccountMeta(pubkey=PublicKey(code_acc), is_signer=False, is_writable=True),
                    AccountMeta(pubkey=system, is_signer=False, is_writable=False),
                ]))
        return (trx, sol)


def getBalance(account):
    return client.get_balance(account, commitment=Confirmed)['result']['value']


def solana2ether(public_key):
    from web3 import Web3
    return bytes(Web3.keccak(bytes(PublicKey(public_key)))[-20:])


ACCOUNT_INFO_LAYOUT = cStruct(
    "type" / Int8ul,
    "eth_acc" / Bytes(20),
    "nonce" / Int8ul,
    "trx_count" / Bytes(8),
    "signer_acc" / Bytes(32),
    "code_acc" / Bytes(32),
    "is_blocked" / Int8ul,
    "blocked_by" / Bytes(32),
)


class AccountInfo(NamedTuple):
    eth_acc: eth_keys.PublicKey
    trx_count: int

    @staticmethod
    def frombytes(data):
        cont = ACCOUNT_INFO_LAYOUT.parse(data)
        return AccountInfo(cont.eth_acc, cont.trx_count)


def getAccountData(client, account, expected_length):
    info = client.get_account_info(account, commitment=Confirmed)['result']['value']
    if info is None:
        raise Exception("Can't get information about {}".format(account))

    data = base64.b64decode(info['data'][0])
    if len(data) != expected_length:
        print("len(data)({}) != expected_length({})".format(len(data), expected_length))
        raise Exception("Wrong data length for account data {}".format(account))
    return data


def getTransactionCount(client, sol_account):
    info = getAccountData(client, sol_account, ACCOUNT_INFO_LAYOUT.sizeof())
    acc_info = AccountInfo.frombytes(info)
    res = int.from_bytes(acc_info.trx_count, 'little')
    print('getTransactionCount {}: {}'.format(sol_account, res))
    return res


def wallet_path():
    res = solana_cli().call("config get")
    substr = "Keypair Path: "
    for line in res.splitlines():
        if line.startswith(substr):
            return line[len(substr):].strip()
    raise Exception("cannot get keypair path")


def send_transaction(client, trx, acc):
    result = client.send_transaction(trx, acc, opts=TxOpts(skip_confirmation=True, preflight_commitment="confirmed"))
    confirm_transaction(client, result["result"])
    result = client.get_confirmed_transaction(result["result"])
    return result
