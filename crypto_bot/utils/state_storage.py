from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from utils import state_io


class StateStorage:
    def read(
        self,
        path: str | Path,
        *,
        default: Any = None,
        strict: bool = False,
    ) -> Any:
        raise NotImplementedError

    def write(
        self,
        path: str | Path,
        value: Any,
        *,
        indent: int = 2,
        timeout: float = state_io.DEFAULT_LOCK_TIMEOUT,
        use_lock: bool = True,
    ) -> None:
        raise NotImplementedError

    def mutate(
        self,
        path: str | Path,
        mutator: Callable[[Any], Any],
        *,
        default: Any = None,
        indent: int = 2,
        timeout: float = state_io.DEFAULT_LOCK_TIMEOUT,
    ) -> Any:
        raise NotImplementedError

    @contextmanager
    def transaction(
        self,
        state_dir: str | Path,
        *,
        timeout: float = state_io.DEFAULT_LOCK_TIMEOUT,
    ) -> Iterator[None]:
        raise NotImplementedError


class JsonStateStorage(StateStorage):
    def read(
        self,
        path: str | Path,
        *,
        default: Any = None,
        strict: bool = False,
    ) -> Any:
        return state_io.read_json_file(path, default=default, strict=strict)

    def write(
        self,
        path: str | Path,
        value: Any,
        *,
        indent: int = 2,
        timeout: float = state_io.DEFAULT_LOCK_TIMEOUT,
        use_lock: bool = True,
    ) -> None:
        state_io.write_json_file(
            path,
            value,
            indent=indent,
            timeout=timeout,
            use_lock=use_lock,
        )

    def mutate(
        self,
        path: str | Path,
        mutator: Callable[[Any], Any],
        *,
        default: Any = None,
        indent: int = 2,
        timeout: float = state_io.DEFAULT_LOCK_TIMEOUT,
    ) -> Any:
        return state_io.mutate_json_file(
            path,
            mutator,
            default=default,
            indent=indent,
            timeout=timeout,
        )

    @contextmanager
    def transaction(
        self,
        state_dir: str | Path,
        *,
        timeout: float = state_io.DEFAULT_LOCK_TIMEOUT,
    ) -> Iterator[None]:
        with state_io.state_transaction_lock(state_dir, timeout=timeout):
            yield


_DEFAULT_STORAGE: StateStorage = JsonStateStorage()


def get_state_storage() -> StateStorage:
    return _DEFAULT_STORAGE
