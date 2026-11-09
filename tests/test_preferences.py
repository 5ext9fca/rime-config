"""Exercise the actual personal Lua processor with a small Rime context stub."""
import ctypes
import ctypes.util
import os
from pathlib import Path
import unittest


class PreferenceTests(unittest.TestCase):
    def test_lua_input_behavior(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / 'config/lua/hx_preferences.lua').exists():
            self.skipTest('Personal assets are excluded from the server image')
        candidates = [ctypes.util.find_library('lua5.4'), ctypes.util.find_library('lua5.3'), '/usr/lib64/liblua-5.4.so']
        lib = None
        for candidate in candidates:
            if candidate:
                try:
                    lib = ctypes.CDLL(candidate)
                    break
                except OSError:
                    pass
        if lib is None:
            self.skipTest('Requires a Lua 5.3/5.4 shared library')
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadfilex.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_void_p]
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]
        state = lib.luaL_newstate()
        self.assertTrue(state)
        previous = Path.cwd()
        try:
            os.chdir(root)
            lib.luaL_openlibs(state)
            result = lib.luaL_loadfilex(state, b'tests/preferences.lua', None)
            if result == 0:
                result = lib.lua_pcallk(state, 0, 0, 0, 0, None)
            if result:
                self.fail(lib.lua_tolstring(state, -1, None).decode())
        finally:
            lib.lua_close(state)
            os.chdir(previous)
