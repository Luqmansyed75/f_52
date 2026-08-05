"""
Maps speaker IDs to human-readable names
"""
from typing import Dict, Optional


class SpeakerMapper:
    """Maps SPEAKER_XX to actual names."""
    
    def __init__(self):
        self.speaker_map: Dict[str, str] = {}
        self.next_id = 1
    
    def get_name(self, speaker_id: str) -> str:
        """
        Get human-readable name for speaker.
        
        Args:
            speaker_id: Technical speaker ID (e.g., "SPEAKER_00")
            
        Returns:
            Human-readable name (e.g., "Person 1")
        """
        if speaker_id == "unknown":
            return "Unknown Speaker"
        
        if speaker_id not in self.speaker_map:
            self.speaker_map[speaker_id] = f"Person {self.next_id}"
            self.next_id += 1
        
        return self.speaker_map[speaker_id]
    
    def set_name(self, speaker_id: str, name: str) -> None:
        """Manually set a speaker's name."""
        self.speaker_map[speaker_id] = name
    
    def get_all_speakers(self) -> Dict[str, str]:
        """Get all speaker mappings."""
        return self.speaker_map.copy()