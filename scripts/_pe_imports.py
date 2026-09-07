"""列出 PE DLL 导入表名 (20-byte entry)."""
import struct
import sys

def list_imports(path):
    data = open(path, 'rb').read()
    if data[:2] != b'MZ':
        return []
    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    if data[e_lfanew:e_lfanew+4] != b'PE\x00\x00':
        return []
    num_sec = struct.unpack_from('<H', data, e_lfanew+6)[0]
    opt_size = struct.unpack_from('<H', data, e_lfanew+20)[0]
    opt_off = e_lfanew + 24
    magic = struct.unpack_from('<H', data, opt_off)[0]
    is_64 = magic == 0x20b
    sec_off = opt_off + opt_size
    secs = []
    for i in range(num_sec):
        off = sec_off + 40*i
        name = data[off:off+8].rstrip(b'\x00').decode(errors='ignore')
        vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', data, off+8)
        secs.append((name, vaddr, vsize, raddr, rsize))

    def rva_off(rva):
        for n, va, vs, ra, rs in secs:
            if va <= rva < va + rs:
                return ra + (rva - va)
        return None

    ddr_off = opt_off + (112 if is_64 else 96)
    imp_rva = struct.unpack_from('<I', data, ddr_off + 8)[0]
    imp_off = rva_off(imp_rva)
    if imp_off is None:
        return []

    out = []
    seen = set()
    while imp_off < len(data) - 20:
        # 5 个 4-byte 字段 = 20 字节
        ilt, _ts, _fwd, name_rva, _ft = struct.unpack_from('<IIIII', data, imp_off)
        if ilt == 0 and name_rva == 0:
            break
        if name_rva:
            no = rva_off(name_rva)
            if no is not None:
                end = data.find(b'\x00', no, no+512)
                if end > 0:
                    name = data[no:end].decode('utf-8', errors='ignore').strip()
                    if name and name not in seen:
                        out.append(name)
                        seen.add(name)
        imp_off += 20
    return out

if __name__ == '__main__':
    for arg in sys.argv[1:]:
        names = list_imports(arg)
        print(f'[{arg}]  ({len(names)} imports)')
        for n in names:
            print(' ', n)