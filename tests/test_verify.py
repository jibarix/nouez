"""Tests for verify.py's static checks that look at code (python -m unittest tests.test_verify)."""
import importlib.util
import os
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "verify", os.path.join(HERE, "..", ".claude", "skills", "verify", "verify.py"))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def unused(source):
    return [name for _, name in verify.unused_names(textwrap.dedent(source))]


class UnusedNamesTest(unittest.TestCase):
    def test_a_name_read_somewhere_is_used(self):
        self.assertEqual(unused("""
            X = 1
            def f():
                return X
            f()
        """), [])

    def test_each_name_unpacked_is_its_own(self):
        self.assertEqual(unused("USED, STALE = 1, 2\nprint(USED)\n"), ["STALE"])

    def test_a_function_that_only_calls_itself_is_unused(self):
        self.assertEqual(unused("def f(n):\n    return f(n - 1)\n"), ["f"])

    def test_a_local_of_the_same_name_is_not_a_read(self):
        cases = {
            "parameter": "STALE = 1\ndef f(STALE):\n    return STALE\nf(0)\n",
            "lambda parameter": "STALE = 1\nh = lambda STALE: STALE\nh(2)\n",
            "assignment": "STALE = 1\ndef f():\n    STALE = 2\n    return STALE\nf()\n",
            "closure over the outer function's local": """
                STALE = 1
                def f():
                    STALE = 2
                    def g():
                        return STALE
                    return g
                f()
            """,
            "except as": "STALE = 1\ndef f():\n    try:\n        pass\n    except OSError as STALE:\n        return STALE\nf()\n",
            "import": "STALE = 1\ndef f():\n    import STALE\n    return STALE\nf()\n",
            "comprehension variable": "STALE = 1\nprint([STALE for STALE in range(3)])\n",
            "class attribute read in the class body": "STALE = 1\nclass C:\n    STALE = 2\n    Y = STALE\nC()\n",
            "walrus in a nested function's default": """
                STALE = 99
                def f():
                    def g(a=(STALE := 5)):
                        pass
                    return STALE
                f()
            """,
            "walrus in a nested class's base": """
                STALE = 99
                def f():
                    class K((STALE := object)):
                        pass
                    return STALE
                f()
            """,
            "a nonlocal name of a class inside a function": """
                STALE = 1
                def f():
                    STALE = 2
                    class C:
                        nonlocal STALE
                        y = STALE
                    return C
                f()
            """,
        }
        for what, source in cases.items():
            with self.subTest(what):
                self.assertEqual(unused(source), ["STALE"])

    def test_a_decorator_named_like_the_function_reads_the_one_before(self):
        self.assertEqual(unused("""
            def f(fn):
                return fn
            @f
            def f():
                pass
            f()
        """), [])

    def test_a_private_import_alias_in_a_method_is_its_own(self):
        self.assertEqual(unused("""
            _C__x = 1
            class C:
                def m(self):
                    import math as __x
                    return __x.pi
            C().m()
        """), ["_C__x"])

    def test_reads_of_the_modules_name_are_seen(self):
        cases = {
            "global and +=": "X = 1\ndef f():\n    global X\n    X += 1\nf()\n",
            "global in a nested function under a parameter of that name": """
                X = 1
                def f(X):
                    def g():
                        global X
                        return X
                    return g()
                f(0)
            """,
            "default": "X = 3\ndef f(a=X):\n    return a\nf()\n",
            "annotations": "Alias = str\ndef f(x: Alias) -> Alias:\n    return x\nf('a')\n",
            "decorator": "def deco(fn):\n    return fn\n@deco\ndef f():\n    pass\nf()\n",
            "outer read while a nested function binds its own": """
                X = 1
                def f():
                    def g():
                        X = 2
                        return X
                    return X + g()
                f()
            """,
            "method, past the class's own name": "X = 1\nclass C:\n    X = 2\n    def m(self):\n        return X\nC().m()\n",
            "comprehension in a class body": "X = 1\nclass C:\n    X = 2\n    Y = [X for _ in range(2)]\nC()\n",
            "a comprehension's first source": "X = [1]\nprint([X for X in X])\n",
            "a later read after a comprehension variable of that name": "X = 1\ndef f():\n    return [X for X in range(3)] + [X]\nf()\n",
            "walrus in a comprehension binds around it": "def f():\n    [y := n for n in range(3)]\n    return y\nf()\n",
            "class base": "class B:\n    pass\nclass C(B):\n    pass\nC()\n",
            "class body read before the class binds it": "X = 5\nclass C:\n    X = X\nC()\n",
            "class body read after a del": "X = 5\nclass C:\n    X = 1\n    del X\n    Y = X\nC()\n",
            "names read in a subscript loop target": "D = {}\nI = 0\n[0 for D[I] in [5]]\n",
            "a private name inside a class": "_C__x = 42\nclass C:\n    def m(self):\n        return __x\nC().m()\n",
            "del": "X = object()\ndel X\n",
            "a subscript assignment isn't a definition": "D = {}\nD['k'] = 1\n",
            "class body read after a walrus that may not run": "X = 5\nclass C:\n    _ = False and (X := 2)\n    y = X\nC()\n",
            "global in a class inside a function with that parameter": """
                X = 1
                def f(X):
                    class C:
                        global X
                        y = X
                    return C
                f(0)
            """,
            "class in a function reads its name before binding it": """
                X = 1
                def f(X):
                    class C:
                        y = X
                        X = 2
                    return C
                f(0)
            """,
        }
        for what, source in cases.items():
            with self.subTest(what):
                self.assertEqual(unused(source), [])

    @unittest.skipUnless(sys.version_info >= (3, 12), "type parameters are Python 3.12 syntax")
    def test_type_parameters_have_their_own_scope(self):
        self.assertEqual(unused("class Base: pass\ndef f[T: Base](): pass\nf()\n"), [])
        self.assertEqual(unused("class Base: pass\nclass K[T: Base]:\n    def m(self, x: T): pass\nK()\n"), [])
        self.assertEqual(unused("Item = int\ntype Alias = list[Item]\nprint(Alias)\n"), [])
        self.assertEqual(unused("T = 1\ndef f[T](x: T): pass\nf(0)\n"), ["T"])
        self.assertEqual(unused("T = 1\nclass K[T](list[T]): pass\nK()\n"), ["T"])
        self.assertEqual(unused("Old = int\ntype Alias[Old] = list[Old]\nprint(Alias)\n"), ["Old"])
        # a generic method's annotations see the class's names, as the class body does
        self.assertEqual(unused("Alias = int\nclass C:\n    Alias = str\n    def f[T](self, x: Alias): pass\nC()\n"),
                         ["Alias"])
        # a class's type alias is evaluated later, when the class's name may be gone: count the module's
        self.assertEqual(unused("X = int\nclass C:\n    X = str\n    type A = X\nC()\n"), [])
        self.assertEqual(unused("Base = int\nclass C:\n    Base = str\n    def f[T: Base](self): pass\nC()\n"), [])


if __name__ == "__main__":
    unittest.main()
