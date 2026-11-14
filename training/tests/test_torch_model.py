import pickle

from generate_claims import build
from torch_model import TorchTextClassifier


def test_learns_and_behaves_like_a_sklearn_model():
    df = build(1500, 0.25, 0.0, seed=2)
    train, test = df.iloc[:1200], df.iloc[1200:]
    model = TorchTextClassifier(epochs=4).fit(train["text"], train["label"])
    proba = model.predict_proba(test["text"])
    assert proba.shape == (len(test), len(model.classes_))
    assert (model.predict(test["text"]) == test["label"]).mean() > 0.8
    # Survives pickling (that's how it's packaged as model.joblib and logged to MLflow).
    again = pickle.loads(pickle.dumps(model))
    assert (again.predict(test["text"][:20]) == model.predict(test["text"][:20])).all()


def test_text_with_only_unknown_words_still_gets_an_answer():
    df = build(600, 0.0, 0.0, seed=3)
    model = TorchTextClassifier(epochs=1).fit(df["text"], df["label"])
    assert model.predict(["zzzz qqqq"])[0] in model.classes_
