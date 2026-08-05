"""
Speaker diarization using pyannote.audio
"""
import torch
import warnings
import numpy as np
from typing import List, Dict, Tuple
from pyannote.audio import Pipeline
import torchaudio.transforms as T

from core.logger import get_app_logger, get_error_logger

warnings.filterwarnings("ignore")

app_logger = get_app_logger()
error_logger = get_error_logger()


class SpeakerDiarizer:
    """Handles speaker diarization for audio segments."""
    
    def __init__(self, hf_token: str = None, model_name: str = "pyannote/speaker-diarization-3.1"):
        """
        Initialize the diarization pipeline.
        
        Args:
            hf_token: HuggingFace token for accessing the model
            model_name: Name of the diarization model
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.target_sample_rate = 16000
        
        app_logger.info(f"Loading diarization pipeline on {self.device}...")
        
        try:
            self.pipeline = Pipeline.from_pretrained(
                model_name,
                token=hf_token,
            )
            self.pipeline.to(self.device)
            app_logger.info("Diarization pipeline ready!")
        except Exception as e:
            error_logger.error(f"Failed to load diarization pipeline: {e}", exc_info=True)
            raise
    
    def _prepare_audio(self, audio_data: np.ndarray, sample_rate: int) -> Tuple[torch.Tensor, int]:
        """
        Prepare audio data for diarization.
        
        Args:
            audio_data: Audio array (mono or stereo)
            sample_rate: Original sample rate
            
        Returns:
            Tuple of (waveform tensor, sample_rate)
        """
        # Ensure mono
        if audio_data.ndim == 2:
            audio_data = audio_data.mean(axis=1)
        
        # Convert to float32
        audio_data = audio_data.astype(np.float32)
        
        # Create torch tensor
        waveform = torch.from_numpy(audio_data).float().unsqueeze(0)
        
        # Resample if needed
        if sample_rate != self.target_sample_rate:
            resampler = T.Resample(sample_rate, self.target_sample_rate)
            waveform = resampler(waveform)
            sample_rate = self.target_sample_rate
        
        return waveform, sample_rate
    
    def diarize_segment(self, audio_data: np.ndarray, sample_rate: int) -> str:
        """
        Diarize a single audio segment and return the most prominent speaker.
        
        Args:
            audio_data: Audio array
            sample_rate: Sample rate of the audio
            
        Returns:
            Speaker label (e.g., "SPEAKER_00") or "unknown"
        """
        try:
            waveform, sr = self._prepare_audio(audio_data, sample_rate)
            
            audio_input = {
                "waveform": waveform,
                "sample_rate": sr
            }
            
            # Run diarization
            diarization_output = self.pipeline(audio_input)
            diarization = diarization_output.speaker_diarization
            
            # Find the speaker with the most speaking time
            speaker_durations = {}
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                duration = turn.end - turn.start
                speaker_durations[speaker] = speaker_durations.get(speaker, 0) + duration
            
            if speaker_durations:
                # Return the speaker who spoke the most
                dominant_speaker = max(speaker_durations.items(), key=lambda x: x[1])[0]
                return dominant_speaker
            else:
                return "unknown"
                
        except Exception as e:
            error_logger.error(f"Diarization failed: {e}", exc_info=True)
            return "unknown"
    
    def diarize_with_timestamps(
        self, 
        audio_data: np.ndarray, 
        sample_rate: int,
        min_duration: float = 0.3
    ) -> List[Dict]:
        """
        Diarize audio and return detailed speaker segments.
        
        Args:
            audio_data: Audio array
            sample_rate: Sample rate of the audio
            min_duration: Minimum segment duration in seconds
            
        Returns:
            List of dicts with 'speaker', 'start', 'end' keys
        """
        try:
            waveform, sr = self._prepare_audio(audio_data, sample_rate)
            
            audio_input = {
                "waveform": waveform,
                "sample_rate": sr
            }
            
            # Run diarization
            diarization_output = self.pipeline(audio_input)
            diarization = diarization_output.speaker_diarization
            
            # Collect segments
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                duration = turn.end - turn.start
                if duration >= min_duration:
                    segments.append({
                        "speaker": speaker,
                        "start": turn.start,
                        "end": turn.end,
                        "duration": duration
                    })
            
            return segments
            
        except Exception as e:
            error_logger.error(f"Diarization with timestamps failed: {e}", exc_info=True)
            return []