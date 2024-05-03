# coding=utf-8
import string
import struct
import sys
# Handle Java Exception
import java.lang.Exception
# Constants from common
from common import can_demangle
# Objects from common
from common import demangler, DemangledException
# Functions from common
from common import is_address_in_current_program
from common import get_logger
from common import vx_toAddr

from ghidra.program.model.util import CodeUnitInsertionException
from ghidra.program.model.symbol import RefType, SourceType
from vx_structs import *


# The Python module that Ghidra directly launches is always called __main__.  If we import
# everything from that module, this module will behave as if Ghidra directly launched it.
from __main__ import *

logger = get_logger(__name__)

function_name_key_words = ['bzero', 'usrInit', 'bfill']

need_create_function = [0x04, 0x05]

# Prepare VxWorks symbol types

function_name_chaset = string.letters
function_name_chaset += string.digits
function_name_chaset += "_:.<>,*"  # For C++
function_name_chaset += "()~+-=/%"  # For C++ special eg operator+(ZafBignumData const &,long)
ghidra_builtin_types = [
    'bool',
    'byte',
    'complex16',
    'complex32',
    'complex8',
    'doublecomplex',
    'dwfenc',
    'dword',
    'filetime',
    'float10',
    'float16',
    'float2',
    'float4',
    'float8',
    'floatcomplex',
    'guid',
    'imagebaseoffset32',
    'imagebaseoffset64',
    'int16',
    'int3',
    'int5',
    'int6',
    'int7',
    'long',
    'longdouble',
    'longdoublecomplex',
    'longlong',
    'mactime',
    'prel31',
    'qword',
    'sbyte',
    'schar',
    'sdword',
    'segmentedcodeaddress',
    'shiftedaddress',
    'sqword',
    'sword',
    'uchar',
    'uint',
    'uint16',
    'uint3',
    'uint5',
    'uint6',
    'uint7',
    'ulong',
    'ulonglong',
    'undefined',
    'undefined1',
    'undefined2',
    'undefined3',
    'undefined4',
    'undefined5',
    'undefined6',
    'undefined7',
    'undefined8',
    'ushort',
    'wchar_t',
    'wchar16',
    'wchar32',
    'word'
]


def check_is_func_name(function_name):
    """ Check target string is match function name format.

    :param function_name: string to check.
    :return: True if string is match function name format, False otherwise.
    """
    # function name length should less than 512 byte
    if len(function_name) > 512:
        return False

    for c in function_name:
        if (c in function_name_chaset) is False:
            return False

    if function_name.lower() in ghidra_builtin_types:
        return False

    return True


def demangle_function(demangle_string):
    function_name = None
    function_return = None
    function_parameters = None
    function_name_end = len(demangle_string) - 1

    # get parameters
    index = len(demangle_string) - 1
    if demangle_string[-1] == ')':
        # have parameters
        parentheses_count = 0
        while index >= 0:
            if demangle_string[index] == ')':
                parentheses_count += 1

            elif demangle_string[index] == '(':
                parentheses_count -= 1

            index -= 1

            if parentheses_count == 0:
                break

        function_name_end = index

    # get function name
    while index >= 0:
        if demangle_string[index] == ' ':
            temp_data = demangle_string[index + 1:function_name_end + 1]
            if temp_data == "*":
                function_name_end = index
                index -= 1

            elif check_is_func_name(temp_data):
                function_name = temp_data
                break

            else:
                function_name_end = index
                index -= 1

        elif index == 0:
            if demangle_string[function_name_end] == " ":
                temp_data = demangle_string[index:function_name_end]
            else:
                temp_data = demangle_string[index:function_name_end + 1]
            if check_is_func_name(temp_data):
                function_name = temp_data
            break

        else:
            index -= 1

    function_name_start = index
    function_parameters = demangle_string[function_name_end + 1:]

    if index != 0:
        # get function return
        function_return = demangle_string[:function_name_start]

    return function_return, function_name, function_parameters


def demangled_symbol(symbol_string):
    sym_demangled_name = None
    sym_demangled = None
    if can_demangle:
        try:
            sym_demangled = demangler.demangle(symbol_string, True)

            if not sym_demangled:
                # some mangled function name didn't start with mangled prefix
                sym_demangled = demangler.demangle(symbol_string, False)

        except DemangledException as err:
            logger.debug("First pass demangling failed: symbol_string: {}, reason: {}".format(symbol_string, err))
            pass

        except java.lang.Exception as err:
            logger.debug("demangling failed: symbol_string: {}, reason: {}".format(symbol_string, err))

        if not sym_demangled:
            try:
                # Temp fix to handle _ prefix function name by remove _ prefix before demangle
                sym_demangled = demangler.demangle(symbol_string[1:], False)

            except DemangledException as err:
                logger.debug("Second pass demangling failed: symbol_string: {}, reason:{}".format(symbol_string, err))
                pass

            except java.lang.Exception as err:
                logger.debug("demangling failed: symbol_string: {}, reason: {}".format(symbol_string, err))

        if sym_demangled:
            sym_demangled_name = sym_demangled.getSignature(False)

            if sym_demangled_name:
                logger.debug("sym_demangled_name: {}".format(sym_demangled_name))
            else:
                logger.debug("Demangled symbol name for string {} is None.".format(symbol_string))

    return sym_demangled_name


def add_symbol(symbol_name, symbol_name_address, symbol_address, symbol_type):
    symbol_address = vx_toAddr(symbol_address)
    symbol_name_string = symbol_name
    # Get symbol_name
    if symbol_name_address:
        symbol_name_address = vx_toAddr(symbol_name_address)
        logger.debug("Have symbol name {} at address {}.".format(symbol_name_string, symbol_name_address))

        if getDataAt(symbol_name_address):
            logger.debug("Data detected at {}; removing to make room for symbol {}".format(symbol_name_address, symbol_name))
            removeDataAt(symbol_name_address)
        else:
            logger.debug("No data detected at {}. Moving on...".format(symbol_address))


        try:
            symbol_name_string = createAsciiString(symbol_name_address).getValue()
            logger.debug("Created ascii string {} at {}.".format(symbol_name_string, symbol_name_address))
        except CodeUnitInsertionException as err:
            logger.error("Failed to create ascii string for symbol named {} at {}: {}".format(symbol_name, symbol_name_address, err))
        except BaseException as err:
            logger.error("Failed to create ascii string for symbol named {} at {}: {}; returning.".format(symbol_name, symbol_name_address, err))
            return


    if getInstructionAt(symbol_address):
        logger.debug("Instruction detected at {}; removing to make room for symbol {}".format(symbol_address, symbol_name))
        removeInstructionAt(symbol_address)
    else:
        logger.debug("No instruction detected at {}. Moving on...".format(symbol_address))

    # Demangle symName
    try:
        # Demangle symName
        sym_demangled_name = demangled_symbol(symbol_name_string)

        if symbol_name_string and (symbol_type in need_create_function):
            logger.debug("Start disassemble function {} at address {}".format(symbol_name_string, symbol_address.toString()))
            disassemble(symbol_address)
            function = createFunction(symbol_address, symbol_name_string)
            if function:
                function.setName(symbol_name_string, SourceType.USER_DEFINED)

            else:
                # Add original symbol name
                createLabel(symbol_address, symbol_name_string, True)

            logger.debug("function: {}; sym_demangled_name: {}".format(function, sym_demangled_name))

            if function and sym_demangled_name:
                # Add demangled string to comment
                codeUnit = listing.getCodeUnitAt(symbol_address)
                codeUnit.setComment(codeUnit.PLATE_COMMENT, sym_demangled_name)
                # Rename function
                # TODO: demangle_function can probably be replaced. Function objects in the Ghidra API have each
                # of .getName(), .getParameters, and .getReturn.
                function_return, function_name, function_parameters = demangle_function(sym_demangled_name)

                logger.debug("Demangled function name is: {}".format(function_name))
                logger.debug("Demangled function return is: {}".format(function_return))
                logger.debug("Demangled function parameters is: {}".format(function_parameters))

                if function_name:
                    function.setName(function_name, SourceType.USER_DEFINED)
                    # TODO: Add parameters later
                # Add original symbol name
                createLabel(symbol_address, symbol_name_string, True)
            if function is None and sym_demangled_name is not None:
                logger.debug('Function for symbol {} was None. In createFunction, one or more functions overlapped the specified address set.'.format(sym_demangled_name))

        else:
            createLabel(symbol_address, symbol_name_string, True)
            if sym_demangled_name:
                codeUnit = listing.getCodeUnitAt(symbol_address)
                codeUnit.setComment(codeUnit.PLATE_COMMENT, sym_demangled_name)

    except Exception as err:
        logger.error("Create symbol failed: symbol_name: {}, symbol_name_address: {}, symbol_address: {}, symbol_type: {} reason: {}".format(symbol_name_string, symbol_name_address, symbol_address, symbol_type, err))


def fix_symbol_table_structs(symbol_table_start, symbol_table_end, symbol_table_data, vx_version):
    symbol_interval = 16
    dt = vx_5_symtbl_dt
    if vx_version == 6:
        symbol_interval = 20
        dt = vx_6_symtbl_dt
    elif vx_version == 7:
        symbol_interval = 40
        dt = vx_7_symtbl_dt

    # Create symbol table structs
    symbol_table_start_addr = vx_toAddr(symbol_table_start)
    symbol_table_end_addr = vx_toAddr(symbol_table_end)

    sym_length = (symbol_table_end - symbol_table_start) // symbol_interval
    logger.debug("Fixing symbol table with start at {} and end at {} with length {}.".format(symbol_table_start_addr, symbol_table_end_addr, sym_length))
    createLabel(symbol_table_start_addr, "vxSymTbl", True)
    clearListing(symbol_table_start_addr, symbol_table_end_addr)
    vx_symbol_array_data_type = ArrayDataType(dt, sym_length, dt.getLength())
    if True:
        block = getMemoryBlock(symbol_table_start_addr)
        if block:
            logger.info('Attempting to create data at block: %s, start: %s, end: %s' % (block.getName(), block.getStart().toString(), block.getEnd().toString()))
        else:
            logger.info("No block at %X, creating new w/%X bytes" % (symbol_table_start, len(symbol_table_data)))
            createMemoryBlock("vxSymbolTable", symbol_table_start_addr, symbol_table_data, False)
    createData(symbol_table_start_addr, vx_symbol_array_data_type)


def is_vx_symbol_file(file_data, is_big_endian=True):
    # Check key function names
    for key_function in function_name_key_words:
        if key_function not in file_data:
            logger.debug("key function not found")
            return False

    if is_big_endian:
        return struct.unpack('>I', file_data[:4])[0] == len(file_data)

    else:
        return struct.unpack('<I', file_data[:4])[0] == len(file_data)


def get_symbol(symbol_name, symbom_prefix="_"):
    symbol = getSymbol(symbol_name, currentProgram.getGlobalNamespace())
    if not symbol and symbom_prefix:
        symbol = getSymbol("{}{}".format(symbom_prefix, symbol_name), currentProgram.getGlobalNamespace())

    return symbol


def get_function(function_name, function_prefix="_"):
    function = getFunction(function_name)
    if not function and function_prefix:
        function = getFunction("{}{}".format(function_prefix, function_name))

    return function


def fix_symbol_by_chains(head, tail, vx_version):
    symbol_interval = 0x10
    dt = vx_5_symtbl_dt
    if vx_version == 6:
        symbol_interval = 20
        dt = vx_6_symtbl_dt
    elif vx_version == 7:
        symbol_interval = 40
        dt = vx_7_symtbl_dt
    ea = head
    while True:
        prev_symbol_addr = toAddr(getInt(ea))
        symbol_name_address = getInt(ea.add(0x04))
        symbol_dest_address = getInt(ea.add(0x08))
        symbol_type = getByte(ea.add(symbol_interval - 2))
        create_struct(ea, dt)
        # Using symbol_address as default symbol_name.
        symbol_name = "0x{:08X}".format(symbol_dest_address)
        add_symbol(symbol_name, symbol_name_address, symbol_dest_address, symbol_type)

        if getInt(ea) == 0 or ea == tail:
            break

        ea = prev_symbol_addr

    return


def create_struct(data_address, data_struct, overwrite=True):
    if is_address_in_current_program(data_address) is False:
        logger.debug("Can't create data struct at {:#010x} with type {}".format(data_address.getOffset(), data_struct))
        return

    try:
        if overwrite:
            for offset in range(data_struct.getLength()):
                removeDataAt(data_address.add(offset))
        createData(data_address, data_struct)

    except:
        logger.error("Can't create data struct at {:#010x} with type {}".format(data_address.getOffset(), data_struct))
        return


def fix_cl_buff_chain(cl_buff_addr, vx_version=5):
    if vx_version == 5:
        if cl_buff_addr.offset == 0:
            return

        next_cl_buff_addr = cl_buff_addr
        while True:
            if is_address_in_current_program(next_cl_buff_addr):
                create_struct(next_cl_buff_addr, vx_5_cl_buff)
            else:
                return

            next_cl_buff_addr = toAddr(getInt(next_cl_buff_addr))
            if next_cl_buff_addr == cl_buff_addr:
                return


def fix_clpool(clpool_addr, vx_version=5):
    cl_pool_info = {
        "cl_pool_addr": clpool_addr.getOffset(),
        "cl_pool_size": None,
        "cl_pool_num": None,
        "cl_pool_num_free": None,
        "cl_pool_usage": None,
        "cl_head_addr": None,

    }
    if vx_version == 5:
        if clpool_addr.offset == 0:
            return

        if is_address_in_current_program(clpool_addr):
            create_struct(clpool_addr, vx_5_clPool)
            cl_head_addr = toAddr(getInt(clpool_addr.add(0x14)))
            cl_pool_info["cl_pool_size"] = getInt(clpool_addr.add(0x00))
            cl_pool_info["cl_pool_num"] = getInt(clpool_addr.add(0x08))
            cl_pool_info["cl_pool_num_free"] = getInt(clpool_addr.add(0x0c))
            cl_pool_info["cl_pool_usage"] = getInt(clpool_addr.add(0x10))
            cl_pool_info["cl_head_addr"] = cl_head_addr.getOffset()
            fix_cl_buff_chain(cl_head_addr)
            return cl_pool_info


def fix_pool_func_tbl(pool_func_addr, vx_version=5):
    if vx_version == 5:
        if pool_func_addr.offset == 0:
            return

        if is_address_in_current_program(pool_func_addr):
            create_struct(pool_func_addr, vx_5_pool_func_tbl)

        func_offset = 0
        for func_name in vx_5_pool_func_dict:
            func_addr = toAddr(getInt(pool_func_addr.add(func_offset)))
            if is_address_in_current_program(func_addr):
                logger.debug("Create function {} at {:#010x}".format(func_name, func_addr.getOffset()))
                disassemble(func_addr)
                function = createFunction(func_addr, func_name)
                if function:
                    function.setName(func_name, SourceType.USER_DEFINED)

                else:
                    # Add original symbol name
                    createLabel(func_addr, func_name, True)

            func_offset += 0x04


def fix_netpool(netpool_addr, vx_version=5):
    net_pool_info = {
        "pool_addr": netpool_addr.getOffset(),
        "pool_table_addr": None,
        "pool_status_addr": None,
        "pool_func_tbl_addr": None,
        "cl_pool_info": [],
    }
    if vx_version == 5:
        create_struct(netpool_addr, vx_5_net_pool)
        pool_table_addr = netpool_addr.add(0x24)
        logger.info("Found ClPool table at {:#010x}".format(pool_table_addr.getOffset()))
        net_pool_info["pool_table_addr"] = pool_table_addr.getOffset()
        pool_status_addr = toAddr(getInt(netpool_addr.add(0x50)))
        logger.info("Found PoolStat at {:#010x}".format(pool_status_addr.getOffset()))
        net_pool_info["pool_status_addr"] = pool_table_addr.getOffset()
        pool_function_tbl_addr = toAddr(getInt(netpool_addr.add(0x54)))
        logger.info("Found pFuncTbl at {:#010x}".format(pool_function_tbl_addr.getOffset()))
        net_pool_info["pool_func_tbl_addr"] = pool_function_tbl_addr.getOffset()

        for i in range(VX_5_CL_TBL_SIZE):
            offset = i * 0x04
            cl_pool_addr = toAddr(getInt(pool_table_addr.add(offset)))
            cl_pool_info = fix_clpool(cl_pool_addr, vx_version)
            if cl_pool_info:
                net_pool_info["cl_pool_info"].append(cl_pool_info)

        create_struct(pool_status_addr, vx_5_pool_stat)
        fix_pool_func_tbl(pool_function_tbl_addr, vx_version)

    return net_pool_info


def fix_tcb(tcb_addr, vx_version=5):
    tcb_info = {
        "tcb_addr": tcb_addr.getOffset(),
        "task_name": None,
        "task_entry_addr": None,
        "task_entry_name": None,
        "task_stack_base": None,
        "task_stack_limit": None,
        "task_stack_limit_end": None,
    }
    if vx_version == 5:
        create_struct(tcb_addr, vx_5_wind_tcb)
        task_name_ptr = tcb_addr.add(0x34)
        task_name_addr = toAddr(getInt(task_name_ptr))
        task_name = getDataAt(task_name_addr)
        logger.info("Task name is {}".format(task_name))
        tcb_info["task_name"] = task_name
        task_entry_ptr = tcb_addr.add(0x74)
        task_entry_addr = toAddr(getInt(task_entry_ptr))
        tcb_info["task_entry_addr"] = task_entry_addr.getOffset()
        logger.info("Task entry addr is {:#010x}".format(task_entry_addr.getOffset()))
        task_entry_name = getFunctionAt(task_entry_addr)
        tcb_info["task_entry_name"] = task_entry_name
        logger.info("Task entry name is {}".format(task_entry_name))
        task_stack_base_ptr = tcb_addr.add(0x78)
        task_stack_base = toAddr(getInt(task_stack_base_ptr))
        tcb_info["task_stack_base"] = task_stack_base.getOffset()
        logger.info("Task stack_base is {:#010x}".format(task_stack_base.getOffset()))
        task_stack_limit_ptr = tcb_addr.add(0x7c)
        task_stack_limit = toAddr(getInt(task_stack_limit_ptr))
        tcb_info["task_stack_limit"] = task_stack_limit.getOffset()
        logger.info("Task stack_limit is {:#010x}".format(task_stack_limit.getOffset()))
        task_stack_limit_end_ptr = tcb_addr.add(0x80)
        task_stack_limit_end = toAddr(getInt(task_stack_limit_end_ptr))
        tcb_info["task_stack_limit_end"] = task_stack_limit_end.getOffset()
        logger.info("Task stack limit end is {:#010x}".format(task_stack_limit_end.getOffset()))
        return tcb_info
