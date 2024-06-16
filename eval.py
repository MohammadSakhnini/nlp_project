import pickle
from dataset import Lecture
import regex as re
from collections import defaultdict
from openai import OpenAI
import config
import tqdm



class LectureQuestions():
    def __init__(self, 
                 topic: str, 
                 questions: list = [],
                 evaluations: list = [],
                 overall_evaluation: list = [],
                 ) -> None:
        
        self.topic: str = topic
        self.questions: list = questions
        self.evaluations: list = evaluations
        self.overall_evaluation: list = overall_evaluation

        

class Evaluator:
    def __init__(self,
                 dataset_path: str,
                 questions_folder_path: str,
                 question_eval_prompt: dict[str, str] = None,
                 overall_eval_prompt: dict[str, str] = None,
                 ) -> None:
        
        self.lectures: dict[int, Lecture] = pickle.load(
            open(dataset_path, "rb")
        )

        self.questions: dict[int, LectureQuestions] = self.load_questions(
            questions_folder_path
        )

        self.client = OpenAI(
            base_url=config.EVAL_BASE_URL,
            api_key=config.EVAL_API_KEY,
        )

        self.question_eval_prompt: dict[str, str] = {
            'system': 'You are given the task of evaluating an examination question given the lecture content within <lecture> </lecture> and question within <question> </question> tags.  Always provide a response in the following format using the appropriate tags:\n\n <reasoning>explain your evaluation in detail, including the section of the lecture that the question covers and your reasoning for the evaluation in markdown text and close with</reasoning> <relevance>an integer from 0 to 10,  where 0 means irrelevant, 5 is still slightly bad, and 10 means a very important and relevant question; only respond with a single number</relevance> <difficulty>an integer from 0 to 10, where 10 is very very hard, 5 is average, and 0 is a silly question, in context of the student having taken the lecture already; only respond with a single number</difficulty> <answer>answer the given question in detail. If the question has choices, instead reply with only the correct choice, otherwise, reply in length in textual form, explaining your reasoning for the answer in markdown text</answer>',
            'user': '<lecture>{lecture_content}</lecture> <question>{question_content}</question>',
            } if question_eval_prompt is None else question_eval_prompt
        self.overall_eval_prompt = {
            'system': 'You are given the task of evaluating a series of examination questions given the lecture content within <lecture> </lecture> and questions within <questions> </questions> tags. Always provide a response in the following format using the appropriate tags:\n\n <reasoning>explain your evaluation in detail, including the sections of the lecture that the question covers and your reasoning for the evaluation in markdown text and close with</reasoning> <relevance>an integer from 0 to 10,  where 0 means irrelevant, 5 is still slightly bad, and 10 means very important and relevant questions; only respond with a single number encompassing the overall relevance</relevance> <difficulty>an integer from 0 to 10, where 10 is very very hard, 5 is average, and 0 is for silly questions, in context of the student having taken the lecture already; only respond with a single number encompassing the overall difficulty</difficulty> <coverage>an integer from 0 to 10, which describes the coverage of the set of questions of the given lecture, where 0 means the lecture is not covered at all, and 10 means the lecture is fully covered</coverage>',
            'user': '<lecture>{lecture_content}</lecture>; <questions>{question_content}</questions>',
            } if overall_eval_prompt is None else overall_eval_prompt

    
    def load_questions(self, 
                       questions_folder_path: str,
                       ) -> dict[int, LectureQuestions]:
        
        self.questions = defaultdict()
        
        for lecture_index in self.lectures:
            lecture_questions = LectureQuestions(
                self.lectures[lecture_index].topic,
            )
            
            with open(f"{questions_folder_path}/"\
                     +f"{self.lectures[lecture_index].topic}.txt", "r") \
                        as question_file:
                question_text = self.is_question(
                    "\n".join(question_file.readlines()),
                )
                
            lecture_questions.questions = question_text
            self.questions[lecture_index] = lecture_questions

        return dict(self.questions)
    

    def is_question(self,
                    text: str,
                    ) -> list[str]:
        regex = re.compile(config.QUESTION_PATTERN, re.DOTALL)

        matches = regex.findall(text.strip())

        return matches
    

    def extract_tag_content(self,
                            text: str,
                            ) -> dict[str, str]:
        # Define the regex pattern
        pattern = r'<(?P<tag>\w+)>(?P<content>.*?)</(?P=tag)>'

        # Find all matches in the text
        matches = re.finditer(pattern, text, re.DOTALL)

        # Extract and print the content
        result = defaultdict(list)
        for tag_match in matches:
            tag = tag_match.group('tag')
            content = tag_match.group('content')
            result[tag].append(content)

        return dict(result)
    

    def evaluate_lectures(self,
                          ):
        for lecture_index in tqdm.tqdm(self.questions):
            print(f"\nEvaluating lecture {lecture_index}")
            self.questions[lecture_index].evaluations = []

            for question_index, question in \
                    tqdm.tqdm(enumerate(self.questions[lecture_index].questions)):    
                print(f"\nEvaluating question {question_index}")

                messages = [
                    {'role': 'system', 'content': 
                        self.question_eval_prompt['system']},
                    {'role': 'user', 'content': 
                        self.question_eval_prompt['user']\
                            .format(
                                lecture_content=self.lectures[lecture_index].content,
                                question_content=question
                                )},
                ]

                evaluation: dict[str, str] = self.get_eval_completion(
                    messages=messages,
                    required_length=config.QUESTION_EVAL_LENGTH,
                )

                self.questions[lecture_index].evaluations.append(evaluation)

            # Overall coverage
            question_text_all: str = "\n\n".join(self.questions[lecture_index].questions)

            print(f"\nEvaluating all questions of lecture {lecture_index}")

            messages = [
                {'role': 'system', 'content': 
                    self.overall_eval_prompt['system']},
                {'role': 'user', 'content': 
                    self.overall_eval_prompt['user']\
                        .format(
                            lecture_content=self.lectures[lecture_index].content,
                            question_content=question_text_all
                            )},
            ]

            evaluation: dict[str, str] = self.get_eval_completion(
                messages=messages,
                required_length=config.OVERALL_EVAL_LENGTH,
            )

            self.questions[lecture_index].overall_evaluation = evaluation


    def get_eval_completion(self,
                            messages: list[dict],
                            required_length: int,
                            ) -> dict[str, str]:
        evaluation = dict()
        retries = 0
        while len(evaluation) != required_length and retries <= config.EVAL_RETRIES:
            retries += 1
            print(f"Prompting eval model | retries: {retries-1}")
            completion = self.client.chat.completions.create(
                model=config.EVAL_MODEL,
                messages=messages,
                temperature=config.EVAL_TEMPERATURE,
            )

            evaluation = self.extract_tag_content(
                completion.choices[0].message.content
            )
            print(f"Evaluation result parsed with length {len(evaluation)}")

        return evaluation
    

    def get_questions(self,
                     ) -> dict[int, LectureQuestions]:
        return self.questions