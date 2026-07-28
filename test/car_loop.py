def loop(i):
    base_a = 1 + i
    base_b = 0 + i

    res = (base_a * 2 + base_b * 2) * 2
    return res


print(loop(1))
print(loop(2))
print(loop(3))
print(loop(4))