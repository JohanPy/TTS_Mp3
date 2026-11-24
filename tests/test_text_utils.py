import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.reader_mode import reader_extract_content
from text_utils import (
    clean_text_for_tts,
    convertir_chiffres_romains,
    normalize_for_tts,
    prepare_text_for_tts,
    process_inclusive_writing,
)


class TestInclusiveWriting(unittest.TestCase):
    def test_homophones_keep_masculine(self):
        self.assertEqual(process_inclusive_writing("les député·es"), "les députés")
        self.assertEqual(process_inclusive_writing("des salarié·es"), "des salariés")
        self.assertEqual(process_inclusive_writing("Fier.e.s"), "Fiers")
        self.assertEqual(process_inclusive_writing("professionnel·le"), "professionnel")
        self.assertEqual(process_inclusive_writing("professionnel·les"), "professionnels")
        self.assertEqual(process_inclusive_writing("inverti.e.s"), "invertis")
        self.assertEqual(process_inclusive_writing("d’élu·es"), "d’élus")

    def test_eur_trice_euse_are_not_homophones(self):
        self.assertEqual(
            process_inclusive_writing("les spectateur·ices"),
            "les spectatrices et spectateurs",
        )
        self.assertEqual(
            process_inclusive_writing("un·e lecteur·rice"),
            "une ou un lectrice et lecteur",
        )
        self.assertEqual(
            process_inclusive_writing("les auteur·ices"),
            "les autrices et auteurs",
        )
        self.assertEqual(
            process_inclusive_writing("les chercheur·euses"),
            "les chercheuses et chercheurs",
        )
        self.assertEqual(
            process_inclusive_writing("des chercheur·ses"),
            "des chercheuses et chercheurs",
        )

    def test_morphological_variants_and_plurals(self):
        self.assertEqual(
            process_inclusive_writing("divers·es"),
            "diverses et divers",
        )
        self.assertEqual(
            process_inclusive_writing("Taïwanais·es"),
            "Taïwanaises et taïwanais",
        )
        self.assertEqual(
            process_inclusive_writing("Afro-Américain·es"),
            "Afro-Américaines et Afro-Américains",
        )
        self.assertEqual(process_inclusive_writing("juif.ves"), "juives et juifs")
        self.assertEqual(process_inclusive_writing("bon.nes"), "bonnes et bons")
        self.assertEqual(process_inclusive_writing("premier·ère·s"), "premières et premiers")
        self.assertEqual(process_inclusive_writing("tou·te·s"), "toutes et tous")
        self.assertEqual(process_inclusive_writing("tous·tes"), "toutes et tous")
        self.assertEqual(process_inclusive_writing("tou-te-s"), "toutes et tous")

    def test_elisions_and_parentheses(self):
        self.assertEqual(
            process_inclusive_writing("quelqu’un.e"),
            "quelqu’une ou quelqu’un",
        )
        self.assertEqual(
            process_inclusive_writing("d’avocat·es"),
            "d’avocates et d’avocats",
        )
        self.assertEqual(process_inclusive_writing("d’un.e"), "d’une ou d’un")
        self.assertEqual(
            process_inclusive_writing("étudiant(e)"),
            "étudiante et étudiant",
        )
        self.assertEqual(
            process_inclusive_writing("étudiant(e)s"),
            "étudiantes et étudiants",
        )
        self.assertEqual(
            process_inclusive_writing("étudiant(e)(s)"),
            "étudiantes et étudiants",
        )

    def test_neologisms_and_slashes(self):
        self.assertEqual(process_inclusive_writing("il/elle/iel"), "elle ou il")
        self.assertEqual(process_inclusive_writing("Il/elle"), "Elle ou il")
        self.assertEqual(process_inclusive_writing("celleux"), "celles et ceux")
        self.assertEqual(process_inclusive_writing("toustes"), "toutes et tous")
        self.assertEqual(process_inclusive_writing("iels"), "elles et ils")

    def test_non_regression_hyphens_and_domains(self):
        self.assertEqual(
            process_inclusive_writing("un porte-parole à Saint-Étienne"),
            "un porte-parole à Saint-Étienne",
        )
        self.assertEqual(
            process_inclusive_writing("visitez https://elpais.es/mundo"),
            "visitez https://elpais.es/mundo",
        )


class TestRomanNumeralsAndOrdinals(unittest.TestCase):
    def test_centuries_and_detached_sup(self):
        self.assertEqual(convertir_chiffres_romains("au XIXe siècle"), "au 19e siècle")
        self.assertEqual(convertir_chiffres_romains("au XIX e siècle"), "au 19e siècle")
        self.assertEqual(convertir_chiffres_romains("du XVIIIe au XXe siècles"), "du 18e au 20e siècles")
        self.assertEqual(convertir_chiffres_romains("au Ve siècle"), "au 5e siècle")
        self.assertEqual(convertir_chiffres_romains("le 1 er mai"), "le 1er mai")

    def test_republics_reich_arrondissements(self):
        self.assertEqual(convertir_chiffres_romains("la Vème République"), "la 5e République")
        self.assertEqual(convertir_chiffres_romains("la VI e République"), "la 6e République")
        self.assertEqual(convertir_chiffres_romains("la IIIe République"), "la 3e République")
        self.assertEqual(convertir_chiffres_romains("la Ie République"), "la 1re République")
        self.assertEqual(convertir_chiffres_romains("le III e Reich"), "le 3e Reich")
        self.assertEqual(convertir_chiffres_romains("Paris IV"), "Paris 4e")
        self.assertEqual(convertir_chiffres_romains("Xe arrondissement"), "10e arrondissement")

    def test_sovereigns_popes_and_structures(self):
        self.assertEqual(convertir_chiffres_romains("lycée Henri-IV"), "lycée Henri 4")
        self.assertEqual(convertir_chiffres_romains("pape Léon XIV"), "pape Léon 14")
        self.assertEqual(convertir_chiffres_romains("Benoît XVI"), "Benoît 16")
        self.assertEqual(convertir_chiffres_romains("François Ier"), "François 1er")
        self.assertEqual(convertir_chiffres_romains("Charles III"), "Charles 3")
        self.assertEqual(convertir_chiffres_romains("chapitre IV, tome II"), "chapitre 4, tome 2")
        self.assertEqual(convertir_chiffres_romains("Vatican II"), "Vatican 2")

    def test_non_regression_proper_nouns_and_e_commerce(self):
        self.assertEqual(convertir_chiffres_romains("Xi Jinping"), "Xi Jinping")
        self.assertEqual(convertir_chiffres_romains("Le 5 octobre"), "Le 5 octobre")
        self.assertEqual(convertir_chiffres_romains("De Gaulle"), "De Gaulle")
        self.assertEqual(convertir_chiffres_romains("Plan X e-commerce"), "Plan X e-commerce")


class TestCleanAndNormalizeTTS(unittest.TestCase):
    def test_preserves_names_with_numbers(self):
        sample = (
            "Sur TF1, France 5, M6, C8, CCTV13, et L214. "
            "Gemini 4, GPT-4, Claude 3, DeepSeek R1, MD5, CO2, G20, phase N3. "
            "Une surface de 12 m² et 3 km²."
        )
        cleaned = clean_text_for_tts(sample)
        for token in ("TF1,", "France 5,", "M6,", "C8,", "CCTV13,", "L214.", "Gemini 4,", "R1,", "MD5,", "CO2,", "G20,", "N3.", "m²", "km²"):
            self.assertIn(token, cleaned)

    def test_strips_real_footnotes_and_preserves_sentence_starting_with_number(self):
        sample = (
            "Selon cette étude[1], le phénomène augmente12. "
            "La réforme¹² est votée. 14 Juillet est férié. "
            "Voir [le ministre – ndlr] et […] ainsi que [son] discours."
        )
        cleaned = clean_text_for_tts(sample)
        self.assertIn("cette étude, le phénomène augmente.", cleaned)
        self.assertIn("La réforme est votée.", cleaned)
        self.assertIn("14 Juillet est férié.", cleaned)
        self.assertIn("le ministre – note de la rédaction", cleaned)
        self.assertIn("et... ainsi que son discours.", cleaned)

    def test_normalize_and_prepare_pipeline(self):
        raw = (
            'L’article 49.3 au XIX e siècle sur TF1, avec ""des"" spectateur·ices, '
            "n° 12, CO 2, et/ou Gemini 4."
        )
        prepared = prepare_text_for_tts(raw)
        self.assertIn("49 3", prepared)
        self.assertIn("19e siècle", prepared)
        self.assertIn("TF1,", prepared)
        self.assertIn("spectatrices et spectateurs", prepared)
        self.assertIn("numéro 12", prepared)
        self.assertIn("CO2", prepared)
        self.assertIn("et ou", prepared)
        self.assertIn("Gemini 4.", prepared)
        self.assertNotIn('""', prepared)

    def test_reader_mode_no_synthetic_double_quotes(self):
        html = "<html><body><article><p>Un texte avec <strong>un mot en gras</strong> et <em>un autre</em>.</p></article></body></html>"
        extracted = reader_extract_content(html)
        self.assertNotIn('""', extracted)
        self.assertNotIn('"', extracted)
        self.assertIn("un mot en gras", extracted)


if __name__ == "__main__":
    unittest.main()
