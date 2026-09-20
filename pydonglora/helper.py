def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000: crc = (crc << 1) ^ 0x1021
            else: crc <<= 1
            crc &= 0xFFFF
    return crc
assert crc16(b"123456789") == 0x29B1

def cobs_encode(data: bytes) -> bytes:
    output = bytearray()
    code_index = 0
    output.append(0)  # placeholder for code byte

    code = 1

    for byte in data:
        if byte == 0:
            output[code_index] = code
            code_index = len(output)
            output.append(0)  # new code byte
            code = 1
        else:
            output.append(byte)
            code += 1

            if code == 0xFF:
                output[code_index] = code
                code_index = len(output)
                output.append(0)
                code = 1

    output[code_index] = code
    return bytes(output)

def cobs_decode(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        code = data[index]
        if code == 0 and index != len(data)-1: raise ValueError("Invalid COBS data")
        index += 1
        # Copy the block
        for _ in range(code - 1):
            if index >= len(data):
                raise ValueError("Invalid COBS data")

            output.append(data[index])
            index += 1
        # Reconstruct the zero
        if code < 0xFF and index < len(data): output.append(0)
    return bytes(output)