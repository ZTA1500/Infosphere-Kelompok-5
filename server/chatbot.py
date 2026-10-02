import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import FeatureUnion
from scipy.sparse import vstack
import pickle
import re

_NON_CJK = re.compile(r'[^㐀-鿿]+')


def cjk_only(text):
    """Keep only Chinese characters (module-level so the model can be pickled)."""
    return _NON_CJK.sub(' ', str(text))


class SimpleQAChatbot:
    def __init__(self):
        # Word n-grams capture meaning; char n-grams add typo/morphology tolerance
        # ("dimna" still shares 3–5 char grams with "dimana"). Combined via union.
        self.vectorizer = FeatureUnion([
            ('word', TfidfVectorizer(lowercase=True, ngram_range=(1, 2),
                                     max_features=1500)),
            ('char', TfidfVectorizer(lowercase=True, analyzer='char_wb',
                                     ngram_range=(3, 5), max_features=3000)),
            # Mandarin questions: Chinese has no spaces and its characters are
            # rare in this corpus, so they get their own 2-3 character features.
            ('cjk', TfidfVectorizer(preprocessor=cjk_only, analyzer='char_wb',
                                    ngram_range=(2, 3), max_features=2000)),
        ])
        self.questions = []
        self.answers = []
        self.question_vectors = None

        self.metadata = {
            'ids': [],
            'categories': [],
            'keywords': [],
            'difficulties': [],
            'confidences': []
        }

    def preprocess_text(self, text):
        text = str(text).lower()
        text = re.sub(r'[^\w\s]', '', text)
        return text.strip()

    def train(self, xlsx_file_path):
        """Train from a single .xlsx file (kept for backward compatibility)."""
        return self.train_dataframe(pd.read_excel(xlsx_file_path))

    def train_dataframe(self, df):
        """Train from an in-memory DataFrame.

        Lets the pipeline merge several datasets and train once. Drops rows that
        are missing a Question or Answer so a malformed new file can't poison
        the model.
        """
        required_cols = ['Question', 'Answer']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Dataset must have a '{col}' column")

        df = df.dropna(subset=['Question', 'Answer']).reset_index(drop=True)
        if len(df) == 0:
            raise ValueError("Dataset has no usable Question/Answer rows")

        self.questions = df['Question'].apply(self.preprocess_text).tolist()
        self.answers = df['Answer'].tolist()

        # reset then repopulate metadata so repeated training never appends stale data
        self.metadata = {'ids': [], 'categories': [], 'keywords': [],
                         'difficulties': [], 'confidences': []}
        if 'ID' in df.columns:
            self.metadata['ids'] = df['ID'].tolist()
        if 'Category' in df.columns:
            self.metadata['categories'] = df['Category'].tolist()
        if 'Keywords' in df.columns:
            self.metadata['keywords'] = df['Keywords'].tolist()
        if 'Difficulty' in df.columns:
            self.metadata['difficulties'] = df['Difficulty'].tolist()
        if 'Confidence' in df.columns:
            self.metadata['confidences'] = df['Confidence'].tolist()

        self.question_vectors = self.vectorizer.fit_transform(self.questions)

        print(f"   - {len(self.questions)} questions processed")
        try:
            print(f"   - {len(self.vectorizer.get_feature_names_out())} features extracted")
        except Exception:
            print("   - features extracted (word + char n-grams)")

        if self.metadata['categories']:
            unique_categories = set(str(c) for c in self.metadata['categories'])
            print(f"   - {len(unique_categories)} unique categories")
        return self

    def get_answer(self, user_question, threshold=0.5):
        processed_question = self.preprocess_text(user_question)

        user_vector = self.vectorizer.transform([processed_question])

        similarities = cosine_similarity(user_vector, self.question_vectors)[0]

        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])

        # below the threshold → no confident match: caller should "point nothing"
        if best_score < threshold:
            return {
                'answer': "Maaf, saya hanya membantu menunjukkan lokasi ruangan di kampus. "
                          "Coba tanyakan lokasi ruangan, contohnya \"Dimana Admisi?\" atau \"Lokasi LSC?\"",
                'confidence': best_score,
                'matched_question': self.questions[best_idx],
                'matched_index': best_idx,
                'found': False,
                'metadata': {}
            }

        result_metadata = {}
        if self.metadata['ids']:
            result_metadata['id'] = self.metadata['ids'][best_idx]
        if self.metadata['categories']:
            result_metadata['category'] = self.metadata['categories'][best_idx]
        if self.metadata['keywords']:
            result_metadata['keywords'] = self.metadata['keywords'][best_idx]
        if self.metadata['difficulties']:
            result_metadata['difficulty'] = self.metadata['difficulties'][best_idx]
        if self.metadata['confidences']:
            result_metadata['dataset_confidence'] = self.metadata['confidences'][best_idx]

        return {
            'answer': self.answers[best_idx],
            'confidence': best_score,
            'matched_question': self.questions[best_idx],
            'matched_index': best_idx,
            'found': True,
            'metadata': result_metadata
        }

    def add_learned(self, question, answer, metadata=None):
        """Append a new question→answer phrasing without a full retrain.

        Re-uses the existing vectorizer (no refit) so this is cheap and safe to
        call at request time. Returns True if a new variant was actually added.
        """
        proc = self.preprocess_text(question)
        if not proc or proc in self.questions:
            return False
        vec = self.vectorizer.transform([proc])
        self.question_vectors = vstack([self.question_vectors, vec]).tocsr()

        base_len = len(self.questions)          # length BEFORE appending
        self.questions.append(proc)
        self.answers.append(answer)

        md = metadata or {}
        defaults = {
            'ids':          md.get('id', f'L{base_len}'),
            'categories':   md.get('category', 'Learned'),
            'keywords':     md.get('keywords', ''),
            'difficulties': md.get('difficulty', 'Easy'),
            'confidences':  md.get('dataset_confidence', 0.7),
        }
        # keep every metadata column aligned with self.questions
        for key, val in defaults.items():
            arr = self.metadata.get(key)
            if isinstance(arr, list) and len(arr) == base_len:
                arr.append(val)
        return True

    def save_model(self, filepath='chatbot_model.pkl'):
        model_data = {
            'vectorizer': self.vectorizer,
            'questions': self.questions,
            'answers': self.answers,
            'question_vectors': self.question_vectors,
            'metadata': self.metadata
        }
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
        print(f"Model saved to {filepath}")

    def load_model(self, filepath='chatbot_model.pkl'):
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        self.vectorizer = model_data['vectorizer']
        self.questions = model_data['questions']
        self.answers = model_data['answers']
        self.question_vectors = model_data['question_vectors']

        if 'metadata' in model_data:
            self.metadata = model_data['metadata']
        else:
            self.metadata = {
                'ids': [],
                'categories': [],
                'keywords': [],
                'difficulties': [],
                'confidences': []
            }

        print(f"[OK] Model loaded from {filepath}")
