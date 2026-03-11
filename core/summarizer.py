"""Generation du compte rendu de reunion via Ollama (LLM local).

Optimise pour les reunions longues (1-2h) :
- Decoupage intelligent en morceaux de 10 min
- Synthese hierarchique (morceaux -> resume partiel -> CR final)
- Progression detaillee
"""

import logging
from typing import Callable, List, Optional, Tuple

from core.transcriber import TranscriptionResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Tu es un assistant specialise dans la redaction de comptes rendus "
    "de reunion professionnels en francais. Tu produis des documents structures, "
    "precis et factuels a partir de transcriptions de reunions. "
    "Ne fabrique jamais d'informations. Si un element est incertain, indique-le avec [?]."
)

SUMMARY_TEMPLATE = """A partir de la transcription suivante d'une reunion, redige un compte rendu structure et professionnel en francais.

Le compte rendu doit contenir les sections suivantes :
1. **Informations generales** : Date, duree, participants identifies
2. **Ordre du jour / Sujets abordes** : Liste des themes principaux discutes
3. **Synthese des echanges** : Pour chaque sujet, resume des discussions et positions exprimees par chaque participant
4. **Decisions prises** : Liste numerotee des decisions actees durant la reunion
5. **Actions a mener** : Tableau avec [Action | Responsable | Echeance] si identifiable
6. **Points en suspens** : Sujets non resolus necessitant un suivi
7. **Prochaine reunion** : Date/heure si mentionnee dans la transcription

Transcription :
---
{transcript_text}
---

Compte rendu :"""

CHUNK_SUMMARY_TEMPLATE = """Voici la partie {part_num}/{total_parts} d'une transcription de reunion (minutes {start_min}-{end_min}).
Extrais les points cles suivants de cette partie :
- Sujets abordes
- Positions exprimees par chaque participant
- Decisions prises
- Actions mentionnees
- Questions en suspens

Sois concis mais ne perds aucune information importante.

Transcription :
---
{chunk_text}
---

Points cles de cette partie :"""

FINAL_SYNTHESIS_TEMPLATE = """Voici les resumes de {n_parts} parties d'une reunion de {duration_min} minutes.
A partir de ces resumes, produis un compte rendu final structure et complet.

{summary_template}"""


def format_transcript_for_llm(transcript: TranscriptionResult) -> str:
    """Formate la transcription en texte lisible pour le LLM."""
    lines = []
    for seg in transcript.segments:
        speaker = seg.speaker or "Inconnu"
        minutes = int(seg.start) // 60
        seconds = int(seg.start) % 60
        timestamp = f"[{minutes:02d}:{seconds:02d}]"
        lines.append(f"{timestamp} {speaker} : {seg.text}")
    return "\n".join(lines)


class MeetingSummarizer:
    """Genere un compte rendu structure via Ollama."""

    def __init__(self, model: str = "mistral", host: str = "http://localhost:11434"):
        self._model = model
        self._host = host
        self._client = None

    def _get_client(self):
        if self._client is None:
            import ollama
            self._client = ollama.Client(host=self._host)
        return self._client

    def check_available(self) -> Tuple[bool, str]:
        """Verifie que Ollama est lance et que le modele est disponible."""
        try:
            client = self._get_client()
            models = client.list()
            model_names = []
            for m in models.get("models", []):
                name = m.get("name", "")
                base_name = name.split(":")[0]
                model_names.append(base_name)

            if self._model in model_names:
                return True, ""
            else:
                available = ", ".join(model_names) if model_names else "aucun"
                return False, (
                    f"Le modele '{self._model}' n'est pas installe. "
                    f"Modeles disponibles : {available}. "
                    f"Executez 'ollama pull {self._model}' dans un terminal."
                )
        except Exception as e:
            return False, (
                f"Impossible de se connecter a Ollama ({self._host}). "
                f"Verifiez qu'Ollama est lance. Erreur: {e}"
            )

    def generate_minutes(self, transcript: TranscriptionResult,
                         session_date: str = "",
                         custom_instructions: str = "",
                         on_token: Optional[Callable[[str], None]] = None,
                         on_chunk_progress: Optional[Callable[[int, int], None]] = None) -> str:
        """Genere le compte rendu a partir de la transcription.

        Pour les reunions courtes (<30 min) : traitement direct.
        Pour les reunions longues : decoupage en morceaux de 10 min + synthese.
        """
        transcript_text = format_transcript_for_llm(transcript)
        estimated_tokens = len(transcript_text) // 4

        logger.info("Transcription: ~%d tokens estimes, duree: %.0f min",
                     estimated_tokens, transcript.duration / 60)

        # Seuil : ~4000 tokens = ~30 min de reunion
        if estimated_tokens <= 4000:
            return self._direct_summarize(transcript_text, custom_instructions, on_token)
        else:
            return self._chunked_summarize(
                transcript, custom_instructions, on_token, on_chunk_progress,
            )

    def _direct_summarize(self, transcript_text: str,
                           custom_instructions: str,
                           on_token: Optional[Callable[[str], None]]) -> str:
        """Traitement direct pour les reunions courtes."""
        client = self._get_client()

        prompt = SUMMARY_TEMPLATE.format(transcript_text=transcript_text)
        if custom_instructions:
            prompt += f"\n\nInstructions supplementaires : {custom_instructions}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info("Generation directe du compte rendu (%s)...", self._model)
        return self._stream_response(client, messages, on_token)

    def _chunked_summarize(self, transcript: TranscriptionResult,
                            custom_instructions: str,
                            on_token: Optional[Callable[[str], None]],
                            on_chunk_progress: Optional[Callable[[int, int], None]]) -> str:
        """Synthese hierarchique pour les reunions longues.

        Strategie en 3 etapes :
        1. Decouper en morceaux de 10 min
        2. Resumer chaque morceau individuellement
        3. Si trop de resumes, regrouper par blocs de 4-5 resumes
        4. Synthese finale a partir des resumes
        """
        client = self._get_client()

        # Morceaux de 10 min (au lieu de 15) pour rester dans la fenetre de contexte
        chunks = self._split_transcript(transcript, chunk_duration_sec=600)
        n_chunks = len(chunks)
        logger.info("Decoupage en %d morceaux de ~10 min", n_chunks)

        # Etape 1 : resumer chaque morceau
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            if on_chunk_progress:
                on_chunk_progress(i + 1, n_chunks)

            logger.info("Resume du morceau %d/%d (%.0f-%.0f min)...",
                         i + 1, n_chunks,
                         chunk.segments[0].start / 60 if chunk.segments else 0,
                         chunk.segments[-1].end / 60 if chunk.segments else 0)

            chunk_text = format_transcript_for_llm(chunk)
            start_min = int(chunk.segments[0].start / 60) if chunk.segments else 0
            end_min = int(chunk.segments[-1].end / 60) if chunk.segments else 0

            prompt = CHUNK_SUMMARY_TEMPLATE.format(
                part_num=i + 1,
                total_parts=n_chunks,
                start_min=start_min,
                end_min=end_min,
                chunk_text=chunk_text,
            )

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            summary = self._get_response(client, messages)
            chunk_summaries.append(
                f"### Minutes {start_min}-{end_min}\n{summary}"
            )

        # Etape 2 : si > 8 morceaux (>80 min), regrouper les resumes par blocs
        if len(chunk_summaries) > 8:
            chunk_summaries = self._merge_summaries(client, chunk_summaries, batch_size=4)

        # Etape 3 : synthese finale
        all_summaries = "\n\n".join(chunk_summaries)
        logger.info("Synthese finale a partir de %d resumes...", len(chunk_summaries))

        summary_section = SUMMARY_TEMPLATE.format(transcript_text=all_summaries)
        final_prompt = FINAL_SYNTHESIS_TEMPLATE.format(
            n_parts=n_chunks,
            duration_min=int(transcript.duration / 60),
            summary_template=summary_section,
        )
        if custom_instructions:
            final_prompt += f"\n\nInstructions supplementaires : {custom_instructions}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": final_prompt},
        ]

        return self._stream_response(client, messages, on_token)

    def _merge_summaries(self, client, summaries: List[str], batch_size: int = 4) -> List[str]:
        """Fusionne les resumes par lots pour reduire le nombre d'entrees."""
        merged = []
        for i in range(0, len(summaries), batch_size):
            batch = summaries[i:i + batch_size]
            if len(batch) == 1:
                merged.append(batch[0])
                continue

            combined = "\n\n".join(batch)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Voici les resumes de {len(batch)} parties consecutives d'une reunion. "
                    f"Fusionne-les en un seul resume coherent, sans perdre d'information.\n\n"
                    f"{combined}\n\nResume fusionne :"
                )},
            ]
            merged_summary = self._get_response(client, messages)
            merged.append(merged_summary)

        logger.info("Resumes fusionnes: %d -> %d", len(summaries), len(merged))
        return merged

    def _stream_response(self, client, messages: list,
                          on_token: Optional[Callable[[str], None]]) -> str:
        """Envoie une requete et streame la reponse."""
        result = ""
        response = client.chat(model=self._model, messages=messages, stream=True)
        for chunk in response:
            token = chunk.get("message", {}).get("content", "")
            result += token
            if on_token:
                on_token(token)
        return result

    def _get_response(self, client, messages: list) -> str:
        """Envoie une requete et retourne la reponse complete."""
        response = client.chat(model=self._model, messages=messages)
        return response.get("message", {}).get("content", "")

    @staticmethod
    def _split_transcript(transcript: TranscriptionResult,
                           chunk_duration_sec: float = 600) -> list:
        """Decoupe une transcription en morceaux temporels."""
        chunks = []
        current_segments = []
        chunk_start = 0.0

        for seg in transcript.segments:
            if seg.start - chunk_start >= chunk_duration_sec and current_segments:
                chunks.append(TranscriptionResult(
                    language=transcript.language,
                    segments=current_segments,
                    duration=seg.start - chunk_start,
                ))
                current_segments = []
                chunk_start = seg.start

            current_segments.append(seg)

        if current_segments:
            chunks.append(TranscriptionResult(
                language=transcript.language,
                segments=current_segments,
                duration=transcript.duration - chunk_start,
            ))

        return chunks
