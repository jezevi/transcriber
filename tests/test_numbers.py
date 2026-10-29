import unittest

from transcheck.numbers import number_to_words, spell_numeric_token


class NumberWords(unittest.TestCase):
    def test_basic(self):
        cases = {
            0: "ноль", 1: "один", 2: "два", 5: "пять", 10: "десять", 11: "одиннадцать", 14: "четырнадцать",
            20: "двадцать", 21: "двадцать один", 45: "сорок пять", 67: "шестьдесят семь",
            100: "сто", 123: "сто двадцать три", 900: "девятьсот", 999: "девятьсот девяносто девять",
            1000: "одна тысяча", 2000: "две тысячи", 5000: "пять тысяч", 11000: "одиннадцать тысяч",
            21000: "двадцать одна тысяча", 22000: "двадцать две тысячи", 112000: "сто двенадцать тысяч",
            2026: "две тысячи двадцать шесть", 1_000_000: "один миллион", 2_500_000: "два миллиона пятьсот тысяч",
            1_000_001: "один миллион один", 5_000_000_000: "пять миллиардов",
        }
        for n, words in cases.items():
            with self.subTest(n=n):
                self.assertEqual(number_to_words(n), words)

    def test_out_of_range(self):
        for bad in (-1, 10**12):
            with self.assertRaises(ValueError):
                number_to_words(bad)

    def test_every_number_up_to_thousand_is_spelled_without_double_spaces(self):
        for n in range(0, 3001):
            w = number_to_words(n)
            self.assertEqual(w, " ".join(w.split()), n)
            self.assertTrue(w and all("а" <= c <= "я" or c == " " for c in w), (n, w))

    def test_spell_token(self):
        self.assertEqual(spell_numeric_token("45"), "сорок пять")
        self.assertEqual(spell_numeric_token("+7"), "плюс семь")
        self.assertEqual(spell_numeric_token("+"), "плюс")
        self.assertEqual(spell_numeric_token("№"), "номер")
        self.assertEqual(spell_numeric_token("№5"), "номер пять")
        self.assertEqual(spell_numeric_token("0"), "ноль")

    def test_spell_token_refuses_what_it_cannot_do(self):
        for w in ("007", "5g", "3,5", "%", "$", "1234567890123", "²", "12a"):
            with self.subTest(w=w):
                self.assertIsNone(spell_numeric_token(w))


if __name__ == "__main__":
    unittest.main()
