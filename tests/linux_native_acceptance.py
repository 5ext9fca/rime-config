"""Linux librime 原生快照隔离验收。

示例：python3 tests/linux_native_acceptance.py --manager /usr/bin/rime_dict_manager
      --workspace private/linux-native
复用跨平台 dict-manager CLI 验收流程；不访问活动数据库、不作为生产同步包装器。
"""
from macos_native_acceptance import main

if __name__ == '__main__':
    main()
