from collections.abc import Sequence


class A:
    pass


class B(A):
    pass


def get_list() -> Sequence[A]:
    b_list: Sequence[B] = [B(), B()]
    return b_list
