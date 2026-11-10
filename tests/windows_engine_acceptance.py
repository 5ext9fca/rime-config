"""Run installed Rime engine on a private copy, never on active user databases."""
import argparse
import ctypes as C
import json
from pathlib import Path
import shutil
import tempfile

from windows_native_acceptance import Traits, function


class Composition(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('length', 'cursor_pos', 'sel_start', 'sel_end')] + [('preedit', C.c_char_p)]


class Candidate(C.Structure):
    _fields_ = [('text', C.c_char_p), ('comment', C.c_char_p), ('reserved', C.c_void_p)]


class Menu(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('page_size', 'page_no', 'is_last_page', 'highlighted_candidate_index', 'num_candidates')] + [('candidates', C.POINTER(Candidate)), ('select_keys', C.c_char_p)]


class Context(C.Structure):
    _fields_ = [('data_size', C.c_int), ('composition', Composition), ('menu', Menu),
                ('preview', C.c_char_p), ('select_labels', C.POINTER(C.c_char_p))]


class Commit(C.Structure):
    _fields_ = [('data_size', C.c_int), ('text', C.c_char_p)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='engine-acceptance-', dir=args.workspace)).resolve()
    user = root / 'user'
    user.mkdir()
    for p in args.source.iterdir():
        if p.is_file() and p.suffix in ('.yaml', '.txt', '.gram') and p.name not in ('installation.yaml', 'user.yaml'):
            shutil.copy2(p, user / p.name)
        elif p.is_dir() and p.name in ('build', 'lua', 'opencc', 'cn_dicts', 'en_dicts', 'icons'):
            shutil.copytree(p, user / p.name)
    (user / 'installation.yaml').write_text('installation_id: engine-acceptance\n')
    logs = root / 'logs'
    logs.mkdir()
    lib = C.CDLL(str(args.dll.resolve()))
    traits = Traits()
    traits.data_size = C.sizeof(Traits) - 4
    traits.shared_data_dir = str(args.dll.parent / 'data').encode('utf-8')
    traits.prebuilt_data_dir = traits.shared_data_dir
    traits.user_data_dir = str(user).encode('utf-8')
    traits.app_name = b'rime.engine_acceptance'
    traits.log_dir = str(logs).encode('utf-8')
    function(lib, 'RimeSetup', None, C.POINTER(Traits))(C.byref(traits))
    function(lib, 'RimeInitialize', None, C.c_void_p)(None)
    sid = function(lib, 'RimeCreateSession', C.c_size_t)()
    assert sid
    select = function(lib, 'RimeSelectSchema', C.c_int, C.c_size_t, C.c_char_p)
    clear = function(lib, 'RimeClearComposition', None, C.c_size_t)
    option = function(lib, 'RimeSetOption', None, C.c_size_t, C.c_char_p, C.c_int)
    get_option = function(lib, 'RimeGetOption', C.c_int, C.c_size_t, C.c_char_p)
    simulate = function(lib, 'RimeSimulateKeySequence', C.c_int, C.c_size_t, C.c_char_p)
    get_context = function(lib, 'RimeGetContext', C.c_int, C.c_size_t, C.POINTER(Context))
    free_context = function(lib, 'RimeFreeContext', C.c_int, C.POINTER(Context))
    key = function(lib, 'RimeProcessKey', C.c_int, C.c_size_t, C.c_int, C.c_int)
    def candidates(text):
        clear(sid)
        option(sid, b'ascii_mode', 0)
        assert simulate(sid, text.encode())
        ctx = Context()
        ctx.data_size = C.sizeof(Context) - 4
        assert get_context(sid, C.byref(ctx))
        try:
            result = [ctx.menu.candidates[i].text.decode() for i in range(ctx.menu.num_candidates)]
            return result, ctx.menu.page_size
        finally:
            free_context(C.byref(ctx))
    result = {}
    try:
        for schema in ('rime_ice', 'luna_quanpin'):
            assert select(sid, schema.encode())
            words, page_size = candidates('nihao')
            assert words and any('你' in s for s in words), schema
            assert page_size == 9
            result[schema + '_chinese_candidates'] = 'passed'
        assert select(sid, b'rime_ice')
        words, _ = candidates('hello')
        assert any('hello' in s.lower() for s in words), 'English translator failed'
        result['english_candidates'] = 'passed'
        candidates("xi'an")
        key(sid, 32, 4)  # Control+Space
        assert get_option(sid, b'ascii_mode')
        commit = Commit()
        commit.data_size = C.sizeof(Commit) - 4
        assert function(lib, 'RimeGetCommit', C.c_int, C.c_size_t, C.POINTER(Commit))(sid, C.byref(commit))
        try:
            assert commit.text.decode() == 'xian'
        finally:
            function(lib, 'RimeFreeCommit', C.c_int, C.POINTER(Commit))(C.byref(commit))
        result['ctrl_space_commit_and_toggle'] = 'passed'
        # Verify same-document includes actually resolve to effective algebra.
        for schema in ('melt_eng', 'radical_pinyin'):
            assert select(sid, schema.encode())
            words, _ = candidates('hello' if schema == 'melt_eng' else 'mu')
            assert words, schema + ' has no usable candidates'
            result[schema + '_effective_algebra'] = 'passed'
    finally:
        function(lib, 'RimeDestroySession', C.c_int, C.c_size_t)(sid)
        function(lib, 'RimeFinalize', None)()
    result['active_userdb_touched'] = False
    result['root'] = str(root)
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
