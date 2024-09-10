import os
import tqdm
import numpy as np
import pandas as pd
from helper.general_functions import create_and_write_csv, load_data_from_csv, split_text
from model.DeepCGSR.init import dep_parser
from coarse_gain import get_coarse_score, get_coarse_score_LDA
from fine_gain import get_tbert_model, get_lda_model, get_topic_sentiment_matrix_tbert, get_topic_sentiment_metrix_lda

def merge_fine_coarse_features(data_df, num_factors, groupBy="reviewerID"):
    feature_dict = {}
    for id, df in data_df.groupby(groupBy):
        feature = np.zeros(num_factors)
        list_finefeature = df['fine_feature']
        list_coarse_feature = df['coarse_feature']
        for fine, coarse in zip(list_finefeature, list_coarse_feature):
            try:
                fine_feature = np.fromstring(fine.strip('[]'), dtype=float, sep=' ')
                coarse_feature = float(coarse)
                feature += fine_feature * coarse_feature
            except Exception as e:
                print("Error: ", e)
                continue
        feature_dict[id] = np.array(feature.tolist())  
    return feature_dict

# Extract fine-grained and coarse-grained features
def extract_review_feature(data_df, dictionary, model, dep_parser, topic_word_matrix, word2vec_model, num_topics, method_name="DeepCGSR", is_switch_data = False):
    row_list = []
    print("data_train_size: ", data_df.shape[0])
    for asin, df in tqdm.tqdm(data_df.groupby("asin")):

        if method_name == "DeepCGSR":
            review_text = df["reviewText"].tolist()
            overall = df["overall"].tolist()
        else:
            review_text = df["filteredReviewText"].tolist()
            overall = df["overall_new"].tolist()

        # overall = df["overall"].tolist()
        reviewerID = df["reviewerID"].tolist()
        for i, text in enumerate(review_text):
            try:
                # Convert text về chuỗi rỗng nếu nó là None
                if text is None:
                    text = ""
                fine_feature = np.zeros(num_topics)
                coarse_feature = 0

                if method_name == "DeepCGSR":
                    fine_feature = get_topic_sentiment_metrix_lda(text, dictionary, model, topic_word_matrix, dep_parser, topic_nums=num_topics)
                    coarse_feature = get_coarse_score_LDA(text, word2vec_model)
                    fine_feature = np.clip(fine_feature, -5, 5)
                else:
                    text_chunks = split_text(text) if text else [""]
                    count_null = 0
                    for chunk in text_chunks:
                        if chunk and chunk.strip():
                            try:
                                fine_feature_chunk = get_topic_sentiment_matrix_tbert(chunk, topic_word_matrix, dep_parser, topic_nums=num_topics)
                                coarse_feature_chunk = get_coarse_score(chunk, word2vec_model)
                            except KeyError as e:
                                print(f"Skipping chunk due to missing key in vocabulary: {e}")
                                continue
                        else:
                            count_null += 1
                            # print("Empty or null chunk detected, skipping processing.")
                        fine_feature += fine_feature_chunk
                        coarse_feature += coarse_feature_chunk
                    coarse_feature /= max(1, len(text_chunks) - count_null)
                    fine_feature = np.clip(fine_feature, -5, 5)

                new_row = {'reviewerID': reviewerID[i], 'itemID': asin, 'overall': overall[i],
                           'fine_feature': fine_feature, 'coarse_feature': coarse_feature}
                row_list.append(new_row)
            except Exception as e:
                print(f"Error: {e}, Text: {text}, fine_feature: {fine_feature}")
                continue
    return pd.DataFrame(row_list, columns=['reviewerID', 'itemID', 'overall', 'fine_feature', 'coarse_feature'])

# Global variables to store features
reviewer_feature_dict = {}
item_feature_dict = {}
allFeatureReview = pd.DataFrame(columns=['reviewerID', 'itemID', 'overall', 'unixReviewTime', 'fine_feature', 'coarse_feature'])

def initialize_features(filename, num_factors, method_name):
    # print("Initialize features")
    global reviewer_feature_dict, item_feature_dict
    allreviews_path = "model/DeepCGSR/feature/allFeatureReview_"
    reviewer_path = "model/DeepCGSR/feature/reviewer_feature_"
    item_path = "model/DeepCGSR/feature/item_feature_"
    dictory_path = "model/DeepCGSR/feature"
    
    if method_name == "DeepCGSR":
        allreviews_path = "model/DeepCGSR/feature_originalmethod/allFeatureReview_"
        reviewer_path = "model/DeepCGSR/feature_originalmethod/reviewer_feature_"
        item_path = "model/DeepCGSR/feature_originalmethod/item_feature_"
        dictory_path = "model/DeepCGSR/feature_originalmethod"

    # Initialize or load reviewer features
    if os.path.exists(reviewer_path + filename +".csv"):
        reviewer_feature_dict = load_data_from_csv(reviewer_path + filename +".csv")
    else:
        allFeatureReview = pd.read_csv(allreviews_path + filename +".csv")
        reviewer_feature_dict = merge_fine_coarse_features(allFeatureReview, num_factors, groupBy="reviewerID")
        create_and_write_csv("reviewer_feature_" + filename, reviewer_feature_dict, method_name)
        
    # Initialize or load item features
    if os.path.exists(item_path+ filename +".csv"):
        item_feature_dict = load_data_from_csv(item_path+ filename +".csv")
    else:
        allFeatureReview = pd.read_csv(allreviews_path+ filename +".csv")
        item_feature_dict = merge_fine_coarse_features(allFeatureReview, num_factors, groupBy="itemID")
        create_and_write_csv("item_feature_" + filename, item_feature_dict, method_name)
    return reviewer_feature_dict, item_feature_dict
        
def extract_features(data_df, split_data, word2vec_model, num_topics, num_words, filename, method_name, is_switch_data=False):
    
    if method_name == "DeepCGSR":
        allreviews_path = "model/DeepCGSR/feature_originalmethod/allFeatureReview_"
    else:
        allreviews_path = "model/DeepCGSR/feature/allFeatureReview_"
    
    if os.path.exists(allreviews_path + filename +".csv"):
        allFeatureReview = pd.read_csv(allreviews_path + filename +".csv")
    else:
        if(method_name == "DeepCGSR"):
            model, dictionary, topic_word_matrix = get_lda_model(split_data, num_topics, num_words)
        else:
            embeddings, model, kmeans, dictionary, topic_word_matrix = get_tbert_model(data_df, split_data, num_topics, num_words, is_switch_data)
        allFeatureReview = extract_review_feature(data_df, dictionary, model, dep_parser, topic_word_matrix, word2vec_model, num_topics, method_name, is_switch_data)
        allFeatureReview.to_csv(allreviews_path + filename +".csv", index=False)
    return allFeatureReview
# run

# initialize_features()