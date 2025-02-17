from typing import Dict
from abc import abstractmethod

import openai
import tiktoken

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoConfig
from accelerate import load_checkpoint_and_dispatch

import text_generation as tg


class ResponseModel:
    @abstractmethod
    def get_response(input_text, **kwargs) -> Dict[str, any]:
        return NotImplementedError
    

class AutoHFResponseModel(ResponseModel):
    def __init__(self, 
                 model_name: str,
                 **kwargs) -> None:
        
        self.device = torch.device("cuda")

        # Load model
        config = AutoConfig.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_config(config)
        self.model = load_checkpoint_and_dispatch(model, model_name, device_map = "auto", no_split_module_classes=model._no_split_modules, dtype=torch.float16)
        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

    def get_response(self, input_text: str, **kwargs) -> Dict[str, any]:
        encoded_inputs = self.tokenizer(input_text, return_tensor="pt").to(self.device)

        # Setting generation config; greedy decoding by default
        generation_cfg = {'do_sample': kwargs.get('do_sample', False),
                          'temperature': kwargs.get('temperature', 0),
                          'max_new_tokens': kwargs.get('max_new_tokens', 128),
                          'use_cache': True}

        with torch.no_grad():
            output = self.model.generate(**encoded_inputs, **generation_cfg)
        sequences = output.sequences
        
        all_decoded_text = self.tokenizer.batch_decode(sequences, skip_special_tokens=True)
        
        completions = []
        for decoded_text in all_decoded_text:
            completions.append({"text": decoded_text})

        return {"completions": completions}
    

class TGIResponseModel(ResponseModel):
    def __init__(self,
                 api_base,
                 timeout: int = 10000,
                 **kwargs) -> None:
        self._client = tg.Client(api_base, timeout=timeout)

    def get_response(self, input_text: str, **kwargs) -> Dict[str, any]:

        # Generation cfg
        generation_cfg = {'best_of': kwargs.get('best_of', 1),
                          'do_sample': kwargs.get('do_sample', False),
                          'temperature': kwargs.get('temperature', None),
                          'max_new_tokens': kwargs.get('max_new_tokens', 128)}
        outputs = self._client.generate(input_text, **generation_cfg)
        generated_text = outputs.generated_text

        return {"completions": [generated_text]}


class OpenAIResponseModel(ResponseModel):
    def __init__(self, 
                 api_base: str = None, 
                 api_key: str = None,
                 api_type: str = None,
                 api_version: str = None,
                 engine: str = None,
                 **kwargs):
        
        self.api_base = api_base
        self.api_key = api_key
        self.api_type = api_type
        self.api_version = api_version
        self.engine = engine

    def get_response(self, input_text: str, **kwargs) -> Dict[str, any]:
        def _do_it():
            openai.organization = None
            openai.api_key = self.api_key
            openai.api_base = self.api_base
            openai.api_type = self.api_type
            openai.api_version = self.api_version

            raw_request = {'engine': self.engine,
                           'messages': [{"role": "user", "content": input_text}],
                           'temperature': kwargs.get('temperature', None)}
            extra_cfg=dict(headers={'Host': 'mlop-azure-gateway.mediatek.inc', 'X-User-Id': 'mtk53598'})
            raw_request.update(**extra_cfg)
            return openai.ChatCompletion.create(**raw_request)
        
        try:
            outputs = _do_it()
        except openai.error.OpenAIError as e:
            error: str = f"OpenAI error: {e}"
            print(error)
            
        completions = [c['message']['contnet'] for c in outputs['choices']]
        
        return {"completions": completions}