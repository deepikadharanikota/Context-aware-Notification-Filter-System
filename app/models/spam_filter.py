from transformers import pipeline

spam_classifier = pipeline(
    "text-classification",
    model="mrm8488/bert-tiny-finetuned-sms-spam-detection"
)

def is_spam(text):
    result = spam_classifier(text)[0]
    return result['label'].lower() == 'spam'