def syntax_aliases(x: str) -> dict[str, str]:
    ans = {}
    for x in x.split():
        k, _, v = x.partition(':')
        ans[k] = v
    return ans
