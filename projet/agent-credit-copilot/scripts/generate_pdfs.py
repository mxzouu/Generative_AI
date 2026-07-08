"""Génère les 6 PDF de documentation interne (procédures bancaires fictives).

Rendu direct via reportlab (aucune dépendance système type pandoc/GTK) : chaque PDF a un
titre en page 1, des sections numérotées (pour un chunking propre) et un pied de page avec
le numéro de page -> le tool search_internal_docs peut citer (fichier.pdf, p.N, §X).

Contenu volontairement aligné sur les seuils du modèle (ml/model.py) et sur les 4 cas de
démo (accord / analyse manuelle / refus / escalade) : les réponses aux questions du
conseiller EXISTENT dans les docs, à une page précise.

Usage :  python scripts/generate_pdfs.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)
from reportlab.lib import colors

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent / "data" / "docs"

# --- styles -------------------------------------------------------------------
styles = getSampleStyleSheet()
H_TITLE = ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=22, leading=26, spaceAfter=6)
H_SUB = ParagraphStyle("DocSub", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#555555"), spaceAfter=18)
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceBefore=16, spaceAfter=6, textColor=colors.HexColor("#0B3D6B"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#14568F"))
BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.5, leading=15, alignment=TA_JUSTIFY, spaceAfter=6)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=14, bulletIndent=4, spaceAfter=2)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(2 * cm, 1.2 * cm, doc.doc_title)
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
    canvas.restoreState()


def build_pdf(filename: str, title: str, version: str, sections: list) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / filename
    doc = BaseDocTemplate(str(path), pagesize=A4,
                          leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    doc.doc_title = title
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="tpl", frames=[frame], onPage=_footer)])

    flow = [Paragraph(title, H_TITLE), Paragraph(f"Document interne — {version}", H_SUB)]
    for sec in sections:
        num, heading, blocks = sec
        style = H1 if "." not in num else H2
        flow.append(Paragraph(f"{num} &nbsp; {heading}", style))
        for b in blocks:
            if isinstance(b, tuple) and b[0] == "table":
                t = Table(b[1], hAlign="LEFT", colWidths=b[2] if len(b) > 2 else None)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D6B")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAAAAA")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF3F8")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]))
                flow.extend([t, Spacer(1, 8)])
            elif isinstance(b, tuple) and b[0] == "bullets":
                for item in b[1]:
                    flow.append(Paragraph(f"• {item}", BULLET))
                flow.append(Spacer(1, 4))
            else:
                flow.append(Paragraph(b, BODY))
    doc.build(flow)
    print(f"[OK] {filename}")


# ==============================================================================
# CONTENU DES 6 DOCUMENTS
# ==============================================================================
def documents() -> list:
    P = "politique_octroi_credit.pdf"
    docs = []

    # 1. Politique générale d'octroi -------------------------------------------
    docs.append((P, "Politique Générale d'Octroi de Crédit", "v3.1 — Direction des Risques", [
        ("1", "Objet et champ d'application", [
            "La présente politique définit les principes, règles et responsabilités encadrant l'octroi de "
            "crédits aux particuliers au sein de l'établissement. Elle s'applique à tous les conseillers "
            "clientèle, analystes crédit et responsables d'agence intervenant dans l'instruction d'un dossier.",
            "Tout dossier de crédit doit être instruit dans le respect de cette politique, des procédures "
            "produit associées (crédit immobilier, crédit à la consommation) et de la réglementation en vigueur, "
            "notamment les dispositions relatives à la lutte contre le surendettement.",
        ]),
        ("2", "Principe de décision assistée", [
            "L'établissement met à disposition des conseillers un outil d'aide à la décision fondé sur un "
            "modèle de notation du risque. Ce modèle produit une probabilité de défaut et une recommandation. "
            "En aucun cas la décision d'octroi n'est automatisée : le conseiller demeure seul responsable de la "
            "décision finale (principe du contrôle humain effectif).",
            "L'outil assiste le conseiller en centralisant le score de risque, le profil client, l'historique "
            "et la documentation réglementaire. Il ne se substitue pas à l'analyse humaine du dossier.",
        ]),
        ("3", "Critères d'éligibilité minimaux", [
            "Un dossier n'est recevable que si l'ensemble des critères suivants sont satisfaits :",
            ("bullets", [
                "Le demandeur est majeur, résident fiscal en France et titulaire d'un compte dans l'établissement.",
                "Le taux d'endettement après opération n'excède pas 35 % des revenus nets (cf. §4).",
                "Le reste à vivre est supérieur au seuil défini au §4.2.",
                "Le demandeur ne fait l'objet d'aucune inscription au FICP non régularisée.",
            ]),
        ]),
        ("4", "Taux d'endettement et reste à vivre", [
            "Le taux d'endettement se calcule comme le rapport entre l'ensemble des charges de crédit "
            "(mensualités des crédits en cours + mensualité du crédit sollicité) et les revenus nets mensuels.",
        ]),
        ("4.1", "Seuil d'endettement", [
            "Le taux d'endettement maximal admissible est fixé à 35 %. Un dépassement ne peut être envisagé "
            "qu'à titre exceptionnel, sur dossier motivé, et relève systématiquement d'une analyse manuelle "
            "par un responsable (cf. procédure d'escalade).",
        ]),
        ("4.2", "Reste à vivre minimal", [
            "Le reste à vivre (revenus nets diminués de l'ensemble des charges) ne peut être inférieur à "
            "800 € pour une personne seule, majoré de 300 € par personne à charge.",
        ]),
        ("5", "Rôle du conseiller et validation", [
            "Le conseiller instruit le dossier, sollicite l'outil d'aide à la décision, consulte la présente "
            "documentation en cas de doute réglementaire, puis enregistre une décision motivée : accord, refus, "
            "analyse manuelle ou escalade. Toute décision est horodatée et tracée à des fins d'audit.",
        ]),
        ("6", "Pièces justificatives", [
            ("bullets", [
                "Pièce d'identité en cours de validité.",
                "Trois derniers bulletins de salaire ou bilans (indépendants).",
                "Dernier avis d'imposition.",
                "Trois derniers relevés de compte.",
                "Justificatif de domicile de moins de trois mois.",
            ]),
        ]),
    ]))

    # 2. Grille de scoring et seuils de décision -------------------------------
    docs.append(("grille_scoring_decision.pdf", "Grille de Scoring et Seuils de Décision",
                 "v2.4 — Direction des Risques", [
        ("1", "Principe du score", [
            "Le modèle de scoring produit une probabilité de défaut (PD) comprise entre 0 et 1. Plus la PD "
            "est élevée, plus le risque de non-remboursement est important. La PD est traduite en bande de "
            "risque et en recommandation selon la grille du §2.",
        ]),
        ("2", "Grille de décision", [
            "La correspondance entre probabilité de défaut, bande de risque et orientation est la suivante :",
            ("table", [
                ["Probabilité de défaut", "Bande de risque", "Recommandation"],
                ["Inférieure à 30 %", "Risque faible", "Accord (sous réserve pièces)"],
                ["De 30 % à 60 %", "Risque modéré", "Analyse manuelle approfondie"],
                ["De 60 % à 75 %", "Risque élevé", "Refus recommandé"],
                ["Supérieure ou égale à 75 %", "Risque critique", "Escalade obligatoire — pas de traitement automatique"],
            ], [5 * cm, 4 * cm, 7 * cm]),
        ]),
        ("3", "Seuil critique et interdiction de traitement automatique", [
            "Lorsque la probabilité de défaut est supérieure ou égale à 75 %, le dossier est réputé de risque "
            "critique. Il ne peut faire l'objet d'aucun traitement automatique ni d'une décision individuelle : "
            "il doit être systématiquement escaladé vers un responsable des engagements (cf. procédure "
            "d'escalade, document dédié).",
        ]),
        ("4", "Facteurs pris en compte", [
            "Le score s'appuie notamment sur les facteurs suivants, dont la contribution individuelle à chaque "
            "décision est restituée au conseiller (explication par dossier) :",
            ("bullets", [
                "Taux d'endettement après opération.",
                "Historique d'incidents de paiement sur 12 mois et retard maximum observé.",
                "Type de contrat de travail et ancienneté dans l'emploi.",
                "Revenu net mensuel et montant sollicité.",
                "Ratio garantie / montant demandé.",
            ]),
        ]),
        ("5", "Limites du modèle", [
            "Le score est une aide, non une vérité. Un score favorable ne dispense pas de vérifier la cohérence "
            "du dossier ; un score défavorable peut être nuancé par des éléments non modélisés (épargne, "
            "patrimoine, relation client). Le conseiller documente tout écart entre le score et sa décision.",
        ]),
    ]))

    # 3. Procédure crédit immobilier -------------------------------------------
    docs.append(("procedure_credit_immobilier.pdf", "Procédure d'Octroi — Crédit Immobilier",
                 "v2.3 — Marché des Particuliers", [
        ("1", "Périmètre", [
            "Cette procédure encadre les crédits destinés à l'acquisition, la construction ou les travaux sur "
            "un bien immobilier à usage d'habitation. Les montants concernés vont généralement de 50 000 € à "
            "400 000 €, sur des durées de 120 à 300 mois.",
        ]),
        ("2", "Apport personnel", [
            "Un apport personnel minimal de 10 % du montant de l'opération est requis pour couvrir les frais "
            "de notaire et de garantie. Un apport inférieur relève de l'analyse manuelle.",
        ]),
        ("3", "Garantie", [
            "Tout crédit immobilier est assorti d'une garantie : hypothèque, privilège de prêteur de deniers "
            "ou caution d'un organisme agréé. La valeur de la garantie doit couvrir au minimum le capital "
            "restant dû. Le ratio garantie / montant est un facteur du score.",
        ]),
        ("4", "Assurance emprunteur", [
            "La souscription d'une assurance décès-invalidité est exigée à hauteur de 100 % des quotités sur "
            "au moins une tête. Le coût de l'assurance est intégré au calcul du taux d'endettement.",
        ]),
        ("5", "Durée et taux", [
            "La durée maximale est de 300 mois (25 ans). Le taux nominal de référence est indexé sur le barème "
            "en vigueur ; à la date de rédaction, le taux immobilier de référence est de 3,5 % annuel.",
        ]),
    ]))

    # 4. Procédure crédit consommation -----------------------------------------
    docs.append(("procedure_credit_consommation.pdf", "Procédure d'Octroi — Crédit à la Consommation",
                 "v1.9 — Marché des Particuliers", [
        ("1", "Périmètre", [
            "Cette procédure couvre les crédits affectés (auto) et non affectés (personnel), ainsi que les "
            "crédits renouvelables. Les montants vont de 1 000 € à 40 000 € (jusqu'à 6 000 € pour le "
            "renouvelable), sur des durées de 6 à 84 mois.",
        ]),
        ("2", "Crédit renouvelable — vigilance renforcée", [
            "Le crédit renouvelable présente un risque supérieur. Son taux est plafonné par le taux d'usure. "
            "Un client détenant déjà deux crédits renouvelables actifs fait l'objet d'une analyse manuelle "
            "avant tout nouvel octroi.",
        ]),
        ("3", "Délai de rétractation", [
            "L'emprunteur dispose d'un délai légal de rétractation de 14 jours calendaires à compter de la "
            "signature de l'offre.",
        ]),
        ("4", "Taux de référence", [
            "À la date de rédaction, les taux nominaux de référence sont : crédit auto 4,5 %, crédit personnel "
            "6,5 %, crédit renouvelable 15 % annuel. Ces taux sont indicatifs et soumis au barème en vigueur.",
        ]),
    ]))

    # 5. Réglementation garanties et sûretés -----------------------------------
    docs.append(("reglementation_garanties.pdf", "Réglementation des Garanties et Sûretés",
                 "v1.6 — Direction Juridique", [
        ("1", "Typologie des garanties", [
            "L'établissement retient trois grandes catégories de sûretés :",
            ("bullets", [
                "L'hypothèque : sûreté réelle portant sur un bien immobilier.",
                "Le nantissement : sûreté sur un bien meuble (véhicule, contrat d'assurance-vie, titres).",
                "La caution : engagement d'un tiers (personne physique ou organisme) de se substituer au débiteur.",
            ]),
        ]),
        ("2", "Évaluation de la valeur", [
            "La valeur retenue d'une garantie fait l'objet d'une décote prudentielle. Pour un bien immobilier, "
            "la décote standard est de 20 % de la valeur vénale. Le ratio garantie / montant est intégré au "
            "score de risque.",
        ]),
        ("3", "Mainlevée", [
            "La mainlevée d'une hypothèque intervient après remboursement intégral du crédit garanti. Les frais "
            "de mainlevée sont à la charge de l'emprunteur.",
        ]),
    ]))

    # 6. Traitement des incidents et impayés -----------------------------------
    docs.append(("procedure_incidents_impayes.pdf", "Procédure de Traitement des Incidents et Impayés",
                 "v2.0 — Recouvrement", [
        ("1", "Définitions", [
            "On distingue trois types d'incidents : le retard de paiement (mensualité réglée avec du retard), "
            "l'impayé (mensualité non réglée) et le rejet de prélèvement (défaut de provision). Un incident est "
            "dit régularisé lorsque la somme due a été acquittée.",
        ]),
        ("2", "Impact sur le score", [
            "Le nombre d'incidents sur les 12 derniers mois et le retard maximum observé (en jours) sont des "
            "facteurs majeurs du score de risque. Un retard supérieur à 90 jours est considéré comme un signal "
            "fort de dégradation.",
        ]),
        ("3", "Procédure de relance", [
            ("bullets", [
                "J+1 à J+15 : relance amiable (courriel, SMS, appel).",
                "J+30 : mise en demeure par courrier recommandé.",
                "J+60 : transfert au service recouvrement.",
                "J+90 : déchéance du terme et inscription FICP le cas échéant.",
            ]),
        ]),
        ("4", "Incidence sur une nouvelle demande", [
            "Un client présentant un incident non régularisé ou un retard de plus de 90 jours au cours des 12 "
            "derniers mois voit toute nouvelle demande orientée vers une analyse manuelle, indépendamment du "
            "score obtenu.",
        ]),
    ]))
    return docs


if __name__ == "__main__":
    for filename, title, version, sections in documents():
        build_pdf(filename, title, version, sections)
    print(f"\n{len(documents())} PDF generes dans {DOCS_DIR}")
