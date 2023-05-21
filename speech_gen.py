#speech_gen.py
import random
from io import BytesIO
import re
import logging
import nltk
import traceback
from functools import wraps
from google.cloud import texttospeech
from pydub import AudioSegment

def select_natural_voice(client):
    voices = client.list_voices().voices
    natural_voices = [voice for voice in voices if any(language_code.startswith("en-") for language_code in voice.language_codes)]
    selected_voice = random.choice(natural_voices)

    # Convert the selected voice to a VoiceSelectionParams object
    voice_params = texttospeech.VoiceSelectionParams(
        language_code=selected_voice.language_codes[0],
        ssml_gender=selected_voice.ssml_gender
    )

    return voice_params

def split_text_by_sentence(text, max_chunk_size=4500):
    # Use NLTK's Punkt tokenizer for sentence splitting
    tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')
    sentences = tokenizer.tokenize(text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) > max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            current_chunk += " " + sentence
    chunks.append(current_chunk)
    return chunks

def error_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error while running {func.__name__}: {e}")
            logging.error(traceback.format_exc())
            raise
    return wrapper 

@error_handler
def initiate_tts_client():
    client = texttospeech.TextToSpeechClient()
    logging.info("Connected to Google Text-To-Speech API.")
    return client

@error_handler
def construct_narration(article, construct_narration_text):
    narration_text = construct_narration_text(article)
    logging.info("Narration text constructed successfully.")
    return narration_text

@error_handler
def split_text(text, max_chunk_size):
    chunks = split_text_by_sentence(text, max_chunk_size)
    logging.info("Text split into chunks successfully.")
    return chunks

@error_handler
def synthesize_speech_for_chunk(client, chunk, voice_params, audio_config):
    input_text = texttospeech.SynthesisInput(text=chunk)
    response = client.synthesize_speech(input=input_text, voice=voice_params, audio_config=audio_config)
    audio_segment = AudioSegment.from_file(BytesIO(response.audio_content), format="mp3")
    logging.info("Speech synthesized for chunk successfully.")
    return audio_segment

def save_audio_segments(audio_segments, output_file):
    combined_segments = sum(audio_segments, AudioSegment.empty())
    combined_segments.export(output_file, format='mp3')

def text_to_speech(article, output_file, config, construct_narration_text, select_natural_voice):
    logging.info("Initiating text-to-speech process...")
    
    client = initiate_tts_client()
    voice_params = select_natural_voice(client)

    text = construct_narration(article, construct_narration_text)

    max_chunk_size = config["text_to_speech"]["max_chunk_size"]
    chunks = split_text(text, max_chunk_size)

    audio_segments = []
    speaking_rate = random.uniform(*config["text_to_speech"]["speaking_rate_range"])
    pitch = random.uniform(*config["text_to_speech"]["pitch_range"])

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        pitch=pitch
    )

    logging.info("Synthesizing speech...")
    for chunk in chunks:
        logging.info(f"Processing chunk: {chunk[:50]}...")
        audio_segment = synthesize_speech_for_chunk(client, chunk, voice_params, audio_config)
        audio_segments.append(audio_segment)

    save_audio_segments(audio_segments, output_file)

    return output_file 