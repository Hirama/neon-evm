import base58
import rlp
import json
import os
import time
from web3 import Web3
from web3.auto.gethdev import w3
from solana.rpc.api import Client
import sqlite3

class KeyValueStore(dict):
    def __init__(self, table_name, filename="some.db"):
        self.table_name = table_name
        self.conn = sqlite3.connect(filename, isolation_level=None)
        self.conn.execute('CREATE TABLE IF NOT EXISTS {} (key text unique, value text)'.format(self.table_name))

    def close(self):
        self.conn.commit()
        self.conn.close()

    def __len__(self):
        rows = self.conn.execute('SELECT COUNT(*) FROM {}'.format(self.table_name)).fetchone()[0]
        return rows if rows is not None else 0

    def iterkeys(self):
        c = self.conn.cursor()
        for row in self.conn.execute('SELECT key FROM {}'.format(self.table_name)):
            yield row[0]

    def itervalues(self):
        c = self.conn.cursor()
        for row in c.execute('SELECT value FROM {}'.format(self.table_name)):
            yield row[0]

    def iteritems(self):
        c = self.conn.cursor()
        for row in c.execute('SELECT key, value FROM {}'.format(self.table_name)):
            yield row[0], row[1]

    def keys(self):
        return list(self.iterkeys())

    def values(self):
        return list(self.itervalues())

    def items(self):
        return list(self.iteritems())

    def __contains__(self, key):
        return self.conn.execute('SELECT 1 FROM {} WHERE key = ?'.format(self.table_name), (key,)).fetchone() is not None

    def __getitem__(self, key):
        item = self.conn.execute('SELECT value FROM {} WHERE key = ?'.format(self.table_name), (key,)).fetchone()
        if item is None:
            raise KeyError(key)
        return item[0]

    def __setitem__(self, key, value):
        self.conn.execute('REPLACE INTO {} (key, value) VALUES (?,?)'.format(self.table_name), (key, value))

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        self.conn.execute('DELETE FROM {} WHERE key = ?'.format(self.table_name), (key,))

    def __iter__(self):
        return self.iterkeys()


solana_url = os.environ.get("SOLANA_URL", "https://api.devnet.solana.com")
evm_loader_id = os.environ.get("EVM_LOADER", "eeLSJgWzzxrqKv1UxtRVVH8FX3qCQWUs9QuAjJpETGU")


class Indexer:
    def run(self):
        self.client = Client(solana_url)

        self.last_slot = 0

        while (True):
            # try:
            print("Start indexing", flush=True)

            self.known_transactions = KeyValueStore("known_transactions")
            self.ethereum_trx = KeyValueStore("ethereum_transactions")
            self.eth_sol_trx = KeyValueStore("ethereum_solana_transactions")

            # do indexation
            self.poll()

            self.known_transactions.close()
            self.ethereum_trx.close()
            self.eth_sol_trx.close()

            #     pass
            # except Exception as err:
            #     print("Got exception while indexing. Type(err):%s, Exception:%s", type(err), err, flush=True)
            time.sleep(60)

    def poll(self):
        continue_table = {}
        holder_table = {}
        counter = 0
        minimal_tx = None
        minimal_slot = self.client.get_slot()["result"]
        maximum_slot = 0
        continue_flag = True
        while (continue_flag):
            result = self.client.get_signatures_for_address(evm_loader_id, before=minimal_tx)
            if len(result["result"]) == 0:
                break
            for tx in result["result"]:
                counter += 1
                solana_signature = tx["signature"]

                if solana_signature in self.known_transactions:
                    if tx["slot"] > self.last_slot:
                        self.last_slot = tx["slot"]
                    continue

                if tx["slot"] <= self.last_slot:
                    if len(continue_table) == 0 and len(holder_table) == 0:
                        continue_flag = False
                        break

                if tx["slot"] > maximum_slot:
                    maximum_slot = tx["slot"]

                if tx["slot"] < minimal_slot:
                    minimal_slot = tx["slot"]
                    minimal_tx = solana_signature

                trx = self.client.get_confirmed_transaction(solana_signature)

                if trx['result']['transaction']['message']['instructions'] is not None:
                    for instruction in trx['result']['transaction']['message']['instructions']:
                        instruction_data = base58.b58decode(instruction['data'])

                        if instruction_data[0] == 0x00: # Write
                            print("{:>6} Write 0x{}".format(counter, instruction_data[-20:].hex()), flush=True)
                            write_account = trx['result']['transaction']['message']['accountKeys'][instruction['accounts'][0]]

                            if write_account in holder_table:
                                self.known_transactions[solana_signature] = ''

                                offset = int.from_bytes(instruction_data[4:8], "little")
                                length = int.from_bytes(instruction_data[8:16], "little")
                                data = instruction_data[16:]

                                for index in range(length):
                                    holder_table[write_account][1][1+offset+index] = data[index]

                                signature = holder_table[write_account][1][1:66]
                                length = int.from_bytes(holder_table[write_account][1][66:74], "little")
                                unsigned_msg = holder_table[write_account][1][74:74+length]

                                try:
                                    (eth_trx, eth_signature, from_address) = get_trx_receipts(unsigned_msg, signature)

                                    storage_account = holder_table[write_account][0]

                                    if storage_account in continue_table:
                                        (logs, status, gas_used, return_value, slot) = continue_table[storage_account]
                                        for rec in logs:
                                            rec['transactionHash'] = eth_signature

                                        print(eth_signature, status)

                                        # transactions_glob[eth_signature] = TransactionInfo(eth_trx, slot, logs, status, gas_used, return_value)
                                        self.ethereum_trx[eth_signature] = json.dumps( {
                                            'eth_trx': eth_trx,
                                            'slot': slot,
                                            'logs': logs,
                                            'status': status,
                                            'gas_used': gas_used,
                                            'return_value': return_value
                                        } )

                                        del continue_table[storage_account]
                                    else:
                                        print("Storage not found")
                                        print(eth_signature, "unknown")
                                        # raise

                                    del holder_table[write_account]
                                except Exception as err:
                                    print("could not parse trx", err)
                                    pass

                        if instruction_data[0] == 0x01: # Finalize
                            print("{:>6} Finalize 0x{}".format(counter, instruction_data.hex()), flush=True)
                            self.known_transactions[solana_signature] = ''
                            pass

                        if instruction_data[0] == 0x02: # CreateAccount
                            print("{:>6} CreateAccount 0x{}".format(counter, instruction_data[-21:-1].hex()), flush=True)
                            self.known_transactions[solana_signature] = ''
                            pass

                        if instruction_data[0] == 0x03: # Call
                            print("{:>6} Call 0x{}".format(counter, instruction_data.hex()), flush=True)
                            self.known_transactions[solana_signature] = ''
                            pass

                        if instruction_data[0] == 0x04: # CreateAccountWithSeed
                            print("{:>6} CreateAccountWithSeed 0x{}".format(counter, instruction_data.hex()), flush=True)
                            self.known_transactions[solana_signature] = ''
                            pass

                        if instruction_data[0] == 0x05: # CallFromRawTrx
                            print("{:>6} CallFromRawTrx 0x{}".format(counter, instruction_data.hex()), flush=True)
                            self.known_transactions[solana_signature] = ''

                            # collateral_pool_buf = instruction_data[1:5]
                            # from_addr = instruction_data[5:25]
                            sign = instruction_data[25:90]
                            unsigned_msg = instruction_data[90:]

                            (eth_trx, eth_signature, from_address) = get_trx_receipts(unsigned_msg, signature)

                            (logs, status, gas_used, return_value, slot) = get_trx_results(trx)
                            for rec in logs:
                                rec['transactionHash'] = eth_signature

                            print(eth_signature, status)

                            # transactions_glob[eth_signature] = TransactionInfo(eth_trx, slot, logs, status, gas_used, return_value)
                            self.ethereum_trx[eth_signature] = json.dumps( {
                                'eth_trx': eth_trx,
                                'slot': slot,
                                'logs': logs,
                                'status': status,
                                'gas_used': gas_used,
                                'return_value': return_value
                            } )

                        if instruction_data[0] == 0x09: # PartialCallFromRawEthereumTX
                            print("{:>6} PartialCallFromRawEthereumTX 0x{}".format(counter, instruction_data.hex()), flush=True)
                            storage_account = trx['result']['transaction']['message']['accountKeys'][instruction['accounts'][0]]

                            if storage_account in continue_table:
                                self.known_transactions[solana_signature] = ''

                                # collateral_pool_buf = instruction_data[1:5]
                                # step_count = instruction_data[5:13]
                                # from_addr = instruction_data[13:33]
                                sign = instruction_data[33:98]
                                unsigned_msg = instruction_data[98:]

                                (eth_trx, eth_signature, from_address) = get_trx_receipts(unsigned_msg, sign)

                                (logs, status, gas_used, return_value, slot) = continue_table[storage_account]
                                for rec in logs:
                                    rec['transactionHash'] = eth_signature

                                print(eth_signature, status)

                                # transactions_glob[eth_signature] = TransactionInfo(eth_trx, slot, logs, status, gas_used, return_value)
                                self.ethereum_trx[eth_signature] = json.dumps( {
                                    'eth_trx': eth_trx,
                                    'slot': slot,
                                    'logs': logs,
                                    'status': status,
                                    'gas_used': gas_used,
                                    'return_value': return_value
                                } )

                                del continue_table[storage_account]
                            else:
                                print("Storage not found")
                                pass

                        if instruction_data[0] == 0x0a: # Continue
                            print("{:>6} Continue 0x{}".format(counter, instruction_data.hex()), flush=True)
                            self.known_transactions[solana_signature] = ''

                            got_result = get_trx_results(trx)

                            if got_result is not None:
                                storage_account = trx['result']['transaction']['message']['accountKeys'][instruction['accounts'][0]]
                                continue_table[storage_account] = got_result

                        if instruction_data[0] == 0x0b: # ExecuteTrxFromAccountDataIterative
                            print("{:>6} ExecuteTrxFromAccountDataIterative 0x{}".format(counter, instruction_data.hex()), flush=True)

                            holder_account =  trx['result']['transaction']['message']['accountKeys'][instruction['accounts'][0]]
                            storage_account = trx['result']['transaction']['message']['accountKeys'][instruction['accounts'][1]]

                            if storage_account in continue_table:
                                self.known_transactions[solana_signature] = ''

                                if holder_account in holder_table:
                                    # print("holder_account found")
                                    # print("Strange behavior. Pay attention.")
                                    holder_table[holder_account] = (storage_account, bytearray(128*1024))
                                else:
                                    holder_table[holder_account] = (storage_account, bytearray(128*1024))

                        if instruction_data[0] == 0x0c: # Cancel
                            print("{:>6} Cancel 0x{}".format(counter, instruction_data.hex()), flush=True)
                            self.known_transactions[solana_signature] = ''

                            storage_account = trx['result']['transaction']['message']['accountKeys'][instruction['accounts'][0]]
                            continue_table[storage_account] = (None, None, None, None, None, None)

                        if instruction_data[0] > 0x0c:
                            print("{:>6} Unknown 0x{}".format(counter, instruction_data.hex()), flush=True)

        self.last_slot = maximum_slot


def get_trx_results(trx):
    slot = trx['result']['slot']
    block_number = hex(slot)
    block_hash = '0x%064x'%slot
    got_result = False
    logs = []
    status = "0x1"
    gas_used = 0
    return_value = bytes
    log_index = 0
    for inner in (trx['result']['meta']['innerInstructions']):
        for event in inner['instructions']:
            log = base58.b58decode(event['data'])
            instruction = log[:1]
            if (int().from_bytes(instruction, "little") == 7):  # OnEvent evmInstruction code
                address = log[1:21]
                count_topics = int().from_bytes(log[21:29], 'little')
                topics = []
                pos = 29
                for _ in range(count_topics):
                    topic_bin = log[pos:pos + 32]
                    topics.append('0x'+topic_bin.hex())
                    pos += 32
                data = log[pos:]
                rec = { 'address': '0x'+address.hex(),
                        'topics': topics,
                        'data': '0x'+data.hex(),
                        'transactionLogIndex': hex(0),
                        'transactionIndex': hex(inner['index']),
                        'blockNumber': block_number,
                        # 'transactionHash': trxId, # set when transaction found
                        'logIndex': hex(log_index),
                        'blockHash': block_hash
                    }
                logs.append(rec)
                log_index +=1
            elif int().from_bytes(instruction, "little") == 6:  # OnReturn evmInstruction code
                got_result = True
                if log[1] < 0xd0:
                    status = "0x1"
                else:
                    status = "0x0"
                gas_used = int.from_bytes(log[2:10], 'little')
                return_value = log[10:].hex()

    if got_result:
        return (logs, status, gas_used, return_value, slot)
    else:
        return None


def get_trx_receipts(unsigned_msg, signature):
    eth_trx = rlp.decode(unsigned_msg)

    eth_trx[6] = int(signature[64]) + 35 + 2 * int.from_bytes(eth_trx[6], "little")
    eth_trx[7] = signature[:32]
    eth_trx[8] = signature[32:64]

    eth_trx_raw = rlp.encode(eth_trx)

    eth_signature = '0x' + bytes(Web3.keccak(eth_trx_raw)).hex()
    from_address = w3.eth.account.recover_transaction(eth_trx_raw.hex())

    # print(eth_trx[3])
    if eth_trx[3]:
        print("recipient_eth", '0x' + eth_trx[3].hex())
    else:
        contract_eth = '0x' + bytes(Web3.keccak(rlp.encode((bytes.fromhex(from_address[2:]), eth_trx[0]))))[-20:].hex()
        print("contract_eth", contract_eth)

    return (eth_trx_raw.hex(), eth_signature, from_address)


indexer = Indexer()
indexer.run()